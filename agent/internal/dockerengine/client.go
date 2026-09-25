// Package dockerengine talks to the local Docker daemon's Engine API
// directly over its Unix domain socket — no `docker` CLI shelling, no
// vendored SDK. This continues the house style validate_app.go already
// established for its read-only daemon-reachability probe, but wraps it in
// a real net/http.Client (via a Unix-socket Transport) so the rest of the
// Linux adapter isn't hand-rolling HTTP/1.1 request/response framing for
// every operation, the way that one probe does.
//
// Every exported method here is a fixed, structured API call built from
// validated Go values — never a string assembled from Control Plane input
// passed to a shell. That is the same safety property the Windows adapter's
// `runCommand` (a fixed argv, never a shell) gives; this package is its
// Docker-daemon equivalent.
package dockerengine

import (
	"archive/tar"
	"bytes"
	"context"
	"encoding/binary"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strconv"
	"strings"
)

// DefaultSocket is where the Docker daemon listens on essentially every
// Linux install (rootful or the common rootless-with-this-path setups).
const DefaultSocket = "/var/run/docker.sock"

// Client is a thin, structured wrapper over the Docker Engine API. Requests
// are made without an explicit API version prefix (matching the existing
// dockerAvailableCheck probe) — the daemon serves its latest supported
// version for an unprefixed path.
type Client struct {
	http       *http.Client
	socketPath string
}

// New returns a Client dialing the default Docker socket, unless
// HEALER_DOCKER_SOCKET overrides it — the seam the dispatcher's own tests
// use to point at a fake daemon instead of a real one, without threading a
// Client through every handler's signature.
func New() *Client {
	if socket := os.Getenv("HEALER_DOCKER_SOCKET"); socket != "" {
		return NewWithSocket(socket)
	}
	return NewWithSocket(DefaultSocket)
}

// NewWithSocket is New, but against an explicit socket path — used by tests
// against a fake Docker daemon listening on a temp-dir socket.
func NewWithSocket(socketPath string) *Client {
	return &Client{
		socketPath: socketPath,
		http: &http.Client{
			Transport: &http.Transport{
				DialContext: func(ctx context.Context, _, _ string) (net.Conn, error) {
					var d net.Dialer
					return d.DialContext(ctx, "unix", socketPath)
				},
			},
		},
	}
}

// apiError is the Docker daemon's standard JSON error body: {"message": "..."}.
type apiError struct {
	Message string `json:"message"`
}

func (c *Client) do(ctx context.Context, method, path string, body io.Reader, contentType string) (*http.Response, error) {
	req, err := http.NewRequestWithContext(ctx, method, "http://docker"+path, body)
	if err != nil {
		return nil, fmt.Errorf("build request: %w", err)
	}
	if contentType != "" {
		req.Header.Set("Content-Type", contentType)
	}
	resp, err := c.http.Do(req)
	if err != nil {
		return nil, fmt.Errorf("docker daemon at %s: %w", c.socketPath, err)
	}
	return resp, nil
}

// readErrorBody consumes and closes resp.Body, returning a descriptive
// error for any non-2xx status.
func readErrorBody(resp *http.Response) error {
	defer resp.Body.Close()
	data, _ := io.ReadAll(io.LimitReader(resp.Body, 1<<16))
	var apiErr apiError
	if json.Unmarshal(data, &apiErr) == nil && apiErr.Message != "" {
		return fmt.Errorf("docker daemon returned HTTP %d: %s", resp.StatusCode, apiErr.Message)
	}
	return fmt.Errorf("docker daemon returned HTTP %d: %s", resp.StatusCode, strings.TrimSpace(string(data)))
}

func isSuccess(status int) bool { return status >= 200 && status < 300 }

// Ping confirms the daemon is reachable and speaking the Engine API.
func (c *Client) Ping(ctx context.Context) error {
	resp, err := c.do(ctx, http.MethodGet, "/_ping", nil, "")
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if !isSuccess(resp.StatusCode) {
		return readErrorBody(resp)
	}
	return nil
}

// Version reports the daemon's own version string, for inspect_host's
// Docker capability report.
func (c *Client) Version(ctx context.Context) (string, error) {
	resp, err := c.do(ctx, http.MethodGet, "/version", nil, "")
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	if !isSuccess(resp.StatusCode) {
		return "", readErrorBody(resp)
	}
	var body struct {
		Version    string `json:"Version"`
		APIVersion string `json:"ApiVersion"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&body); err != nil {
		return "", fmt.Errorf("decode version response: %w", err)
	}
	return fmt.Sprintf("%s (API %s)", body.Version, body.APIVersion), nil
}

// EnsureNetwork makes sure a bridge network with this name exists,
// creating it if not. Idempotent: an existing network is left alone.
func (c *Client) EnsureNetwork(ctx context.Context, name string) error {
	resp, err := c.do(ctx, http.MethodGet, "/networks/"+urlPathEscape(name), nil, "")
	if err != nil {
		return err
	}
	resp.Body.Close()
	if resp.StatusCode == http.StatusOK {
		return nil
	}
	if resp.StatusCode != http.StatusNotFound {
		return fmt.Errorf("checking network %q: HTTP %d", name, resp.StatusCode)
	}

	body, err := json.Marshal(map[string]any{"Name": name, "Driver": "bridge", "CheckDuplicate": true})
	if err != nil {
		return err
	}
	createResp, err := c.do(ctx, http.MethodPost, "/networks/create", bytes.NewReader(body), "application/json")
	if err != nil {
		return err
	}
	defer createResp.Body.Close()
	if !isSuccess(createResp.StatusCode) {
		return readErrorBody(createResp)
	}
	return nil
}

// BuildImage tars up contextDir (respecting the same excludes deploy_release
// already applies to a Windows source snapshot) and POSTs it as a Docker
// build context, tagging the result as tag. dockerfileRelPath is relative to
// contextDir (usually just "Dockerfile").
func (c *Client) BuildImage(ctx context.Context, contextDir, dockerfileRelPath, tag string, excludeDirs map[string]bool) error {
	archive, err := tarDirectory(contextDir, excludeDirs)
	if err != nil {
		return fmt.Errorf("build context for %s: %w", contextDir, err)
	}

	query := "?t=" + urlQueryEscape(tag) + "&dockerfile=" + urlQueryEscape(dockerfileRelPath) + "&rm=1"
	resp, err := c.do(ctx, http.MethodPost, "/build"+query, bytes.NewReader(archive), "application/x-tar")
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if !isSuccess(resp.StatusCode) {
		return readErrorBody(resp)
	}
	return drainBuildStream(resp.Body)
}

// PullImage pulls an immutable image reference (repo[:tag][@digest]).
func (c *Client) PullImage(ctx context.Context, ref string) error {
	name, tag := splitImageRef(ref)
	query := "?fromImage=" + urlQueryEscape(name)
	if tag != "" {
		query += "&tag=" + urlQueryEscape(tag)
	}
	resp, err := c.do(ctx, http.MethodPost, "/images/create"+query, nil, "")
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if !isSuccess(resp.StatusCode) {
		return readErrorBody(resp)
	}
	return drainBuildStream(resp.Body)
}

// RemoveImage removes one named release tag. Docker rejects removal while
// any container still references it; force removal is deliberately absent.
func (c *Client) RemoveImage(ctx context.Context, ref string) error {
	resp, err := c.do(ctx, http.MethodDelete, "/images/"+urlPathEscape(ref), nil, "")
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if isSuccess(resp.StatusCode) || resp.StatusCode == http.StatusNotFound {
		return nil
	}
	return readErrorBody(resp)
}

// drainBuildStream reads a build/pull response — a stream of newline-
// delimited JSON progress objects — to completion, and returns an error if
// any object carries an "error"/"errorDetail" field. The body must be fully
// consumed either way so the connection can be reused/closed cleanly.
func drainBuildStream(body io.Reader) error {
	decoder := json.NewDecoder(body)
	var lastError string
	for {
		var line struct {
			Error       string `json:"error"`
			ErrorDetail struct {
				Message string `json:"message"`
			} `json:"errorDetail"`
		}
		if err := decoder.Decode(&line); err != nil {
			if err == io.EOF {
				break
			}
			return fmt.Errorf("reading docker daemon progress stream: %w", err)
		}
		if line.Error != "" {
			lastError = line.Error
		} else if line.ErrorDetail.Message != "" {
			lastError = line.ErrorDetail.Message
		}
	}
	if lastError != "" {
		return fmt.Errorf("docker reported an error: %s", lastError)
	}
	return nil
}

// ContainerSpec is everything CreateContainer needs to start one instance.
type ContainerSpec struct {
	Image         string
	Env           map[string]string
	Network       string
	HostPort      int
	InternalPort  int
	CPULimit      float64 // fractional CPUs, 0 = unlimited
	MemoryLimitMB int     // 0 = unlimited
}

// CreateContainer creates (but does not start) a container under the given
// name, converging like the Windows adapter's start_instance does: any
// existing container under this name is removed first.
func (c *Client) CreateContainer(ctx context.Context, name string, spec ContainerSpec) (string, error) {
	if err := c.RemoveContainer(ctx, name, true); err != nil {
		return "", fmt.Errorf("removing any existing container named %s: %w", name, err)
	}

	portKey := fmt.Sprintf("%d/tcp", spec.InternalPort)
	env := make([]string, 0, len(spec.Env))
	for k, v := range spec.Env {
		env = append(env, k+"="+v)
	}

	hostConfig := map[string]any{
		"PortBindings": map[string]any{
			portKey: []map[string]string{{"HostIp": "0.0.0.0", "HostPort": strconv.Itoa(spec.HostPort)}},
		},
		"RestartPolicy": map[string]string{"Name": "no"},
	}
	if spec.Network != "" {
		hostConfig["NetworkMode"] = spec.Network
	}
	if spec.MemoryLimitMB > 0 {
		hostConfig["Memory"] = int64(spec.MemoryLimitMB) * 1024 * 1024
	}
	if spec.CPULimit > 0 {
		hostConfig["NanoCpus"] = int64(spec.CPULimit * 1e9)
	}

	body, err := json.Marshal(map[string]any{
		"Image":        spec.Image,
		"Env":          env,
		"ExposedPorts": map[string]any{portKey: map[string]any{}},
		"HostConfig":   hostConfig,
	})
	if err != nil {
		return "", err
	}

	resp, err := c.do(ctx, http.MethodPost, "/containers/create?name="+urlQueryEscape(name), bytes.NewReader(body), "application/json")
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	if !isSuccess(resp.StatusCode) {
		return "", readErrorBody(resp)
	}
	var created struct {
		ID string `json:"Id"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&created); err != nil {
		return "", fmt.Errorf("decode container create response: %w", err)
	}
	return created.ID, nil
}

// StartContainer starts an existing (created) container.
func (c *Client) StartContainer(ctx context.Context, nameOrID string) error {
	resp, err := c.do(ctx, http.MethodPost, "/containers/"+urlPathEscape(nameOrID)+"/start", nil, "")
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	// 304 = already started — treated as success, converging semantics.
	if isSuccess(resp.StatusCode) || resp.StatusCode == http.StatusNotModified {
		return nil
	}
	return readErrorBody(resp)
}

// StopContainer stops a running container within timeoutSeconds, sending
// SIGKILL after. A container that's already stopped or doesn't exist is
// treated as success — the caller's intent is the end state.
func (c *Client) StopContainer(ctx context.Context, nameOrID string, timeoutSeconds int) error {
	path := fmt.Sprintf("/containers/%s/stop?t=%d", urlPathEscape(nameOrID), timeoutSeconds)
	resp, err := c.do(ctx, http.MethodPost, path, nil, "")
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	switch resp.StatusCode {
	case http.StatusOK, http.StatusNoContent, http.StatusNotModified, http.StatusNotFound:
		return nil
	default:
		return readErrorBody(resp)
	}
}

// RemoveContainer removes a container, optionally forcing (killing it
// first if still running). A container that doesn't exist is success.
func (c *Client) RemoveContainer(ctx context.Context, nameOrID string, force bool) error {
	path := "/containers/" + urlPathEscape(nameOrID)
	if force {
		path += "?force=true"
	}
	resp, err := c.do(ctx, http.MethodDelete, path, nil, "")
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if isSuccess(resp.StatusCode) || resp.StatusCode == http.StatusNotFound {
		return nil
	}
	return readErrorBody(resp)
}

// ContainerState is the subset of `docker inspect` this adapter needs.
type ContainerState struct {
	Exists   bool
	Running  bool
	Status   string // "running", "exited", "created", ...
	ExitCode int
}

// InspectContainer reports whether a container exists and its run state.
func (c *Client) InspectContainer(ctx context.Context, nameOrID string) (ContainerState, error) {
	resp, err := c.do(ctx, http.MethodGet, "/containers/"+urlPathEscape(nameOrID)+"/json", nil, "")
	if err != nil {
		return ContainerState{}, err
	}
	defer resp.Body.Close()
	if resp.StatusCode == http.StatusNotFound {
		return ContainerState{Exists: false}, nil
	}
	if !isSuccess(resp.StatusCode) {
		return ContainerState{}, readErrorBody(resp)
	}
	var body struct {
		State struct {
			Status   string `json:"Status"`
			Running  bool   `json:"Running"`
			ExitCode int    `json:"ExitCode"`
		} `json:"State"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&body); err != nil {
		return ContainerState{}, fmt.Errorf("decode container inspect response: %w", err)
	}
	return ContainerState{
		Exists: true, Running: body.State.Running, Status: body.State.Status, ExitCode: body.State.ExitCode,
	}, nil
}

// ContainerLogs returns the last `tail` lines of stdout+stderr, demultiplexed
// from Docker's framed log stream (used for diagnostics when a container
// fails to become healthy — never exposed as an unbounded read).
func (c *Client) ContainerLogs(ctx context.Context, nameOrID string, tail int) (string, error) {
	path := fmt.Sprintf("/containers/%s/logs?stdout=1&stderr=1&tail=%d", urlPathEscape(nameOrID), tail)
	resp, err := c.do(ctx, http.MethodGet, path, nil, "")
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	if !isSuccess(resp.StatusCode) {
		return "", readErrorBody(resp)
	}
	return demuxDockerLogStream(io.LimitReader(resp.Body, 1<<20)), nil
}

// ContainerStreamLogs reads one stream from Docker's bounded recent-log
// endpoint. The byte cap also protects against a single enormous log line.
func (c *Client) ContainerStreamLogs(ctx context.Context, nameOrID, stream string, tail int) (string, error) {
	if stream != "stdout" && stream != "stderr" {
		return "", fmt.Errorf("invalid container log stream %q", stream)
	}
	if tail < 1 || tail > 5000 {
		return "", fmt.Errorf("invalid container log tail %d", tail)
	}
	path := fmt.Sprintf("/containers/%s/logs?%s=1&tail=%d", urlPathEscape(nameOrID), stream, tail)
	resp, err := c.do(ctx, http.MethodGet, path, nil, "")
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	if !isSuccess(resp.StatusCode) {
		return "", readErrorBody(resp)
	}
	data, err := io.ReadAll(io.LimitReader(resp.Body, (1<<20)+1))
	if err != nil {
		return "", fmt.Errorf("read container logs: %w", err)
	}
	if len(data) > 1<<20 {
		return "", fmt.Errorf("container log response exceeds the 1 MiB limit")
	}
	return demuxDockerLogStream(bytes.NewReader(data)), nil
}

// demuxDockerLogStream strips Docker's 8-byte frame headers
// ([stream(1), 0,0,0, size(4 big-endian)]) from a non-TTY container's
// combined log stream, returning the plain text.
func demuxDockerLogStream(r io.Reader) string {
	var out bytes.Buffer
	header := make([]byte, 8)
	for {
		if _, err := io.ReadFull(r, header); err != nil {
			break
		}
		size := binary.BigEndian.Uint32(header[4:8])
		if size == 0 {
			continue
		}
		if _, err := io.CopyN(&out, r, int64(size)); err != nil {
			break
		}
	}
	return out.String()
}

// tarDirectory builds an in-memory tar archive of dir, skipping any
// directory (by basename) named in excludeDirs.
func tarDirectory(dir string, excludeDirs map[string]bool) ([]byte, error) {
	var buf bytes.Buffer
	tw := tar.NewWriter(&buf)

	err := filepath.WalkDir(dir, func(path string, entry os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		rel, err := filepath.Rel(dir, path)
		if err != nil {
			return err
		}
		if rel == "." {
			return nil
		}
		if entry.IsDir() && excludeDirs[strings.ToLower(entry.Name())] {
			return filepath.SkipDir
		}
		info, err := entry.Info()
		if err != nil {
			return err
		}
		header, err := tar.FileInfoHeader(info, "")
		if err != nil {
			return err
		}
		header.Name = filepath.ToSlash(rel)
		if entry.IsDir() {
			header.Name += "/"
			return tw.WriteHeader(header)
		}
		if err := tw.WriteHeader(header); err != nil {
			return err
		}
		file, err := os.Open(path)
		if err != nil {
			return err
		}
		defer file.Close()
		_, err = io.Copy(tw, file)
		return err
	})
	if err != nil {
		return nil, err
	}
	if err := tw.Close(); err != nil {
		return nil, err
	}
	return buf.Bytes(), nil
}

// splitImageRef splits "name:tag" into its parts, defaulting to "latest" —
// careful to split on the LAST colon after the last slash, so a registry
// port ("host:5000/name:tag") isn't mistaken for the tag separator.
func splitImageRef(ref string) (name, tag string) {
	if strings.Contains(ref, "@sha256:") {
		return ref, ""
	}
	lastSlash := strings.LastIndex(ref, "/")
	searchFrom := 0
	if lastSlash >= 0 {
		searchFrom = lastSlash
	}
	if idx := strings.LastIndex(ref[searchFrom:], ":"); idx >= 0 {
		return ref[:searchFrom+idx], ref[searchFrom+idx+1:]
	}
	return ref, "latest"
}

func urlQueryEscape(s string) string { return url.QueryEscape(s) }

// urlPathEscape escapes a single path segment (a container/network name),
// which Docker names restrict to [a-zA-Z0-9_.-] anyway — PathEscape is used
// defensively rather than because exotic characters are expected.
func urlPathEscape(s string) string { return url.PathEscape(s) }
