package dispatcher

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
	"time"

	"github.com/healer-platform/agent/internal/config"
	"github.com/healer-platform/agent/internal/dockerengine"
)

type deploySource struct {
	Type     string  `json:"type"`
	Location string  `json:"location"`
	Ref      *string `json:"ref"`
}

var immutableImageRef = regexp.MustCompile(`^[a-zA-Z0-9][a-zA-Z0-9._:/-]*@sha256:[a-fA-F0-9]{64}$`)
var cleanupSlug = regexp.MustCompile(`^[a-z0-9][a-z0-9-]*$`)
var cleanupVersion = regexp.MustCompile(`^[a-zA-Z0-9][a-zA-Z0-9_.-]*$`)

func validImmutableImageRef(ref string) bool { return immutableImageRef.MatchString(ref) }

type deployWindows struct {
	PythonExecutable string   `json:"python_executable"`
	RequirementsFile string   `json:"requirements_file"`
	ManagePy         string   `json:"manage_py"`
	WSGIModule       string   `json:"wsgi_module"`
	SettingsModule   string   `json:"settings_module"`
	StaticDir        string   `json:"static_dir"`
	MediaDir         string   `json:"media_dir"`
	LogDir           string   `json:"log_dir"`
	Exclude          []string `json:"exclude"`
}

type deployLinux struct {
	InternalPort  int               `json:"internal_port"`
	Env           map[string]string `json:"env"`
	CPULimit      float64           `json:"cpu_limit"`
	MemoryLimitMB int               `json:"memory_limit_mb"`
}

type deployReleasePayload struct {
	Operation      string         `json:"operation,omitempty"`
	Adapter        string         `json:"adapter"`
	AppSlug        string         `json:"app_slug"`
	ReleaseVersion string         `json:"release_version"`
	Source         deploySource   `json:"source"`
	Windows        *deployWindows `json:"windows,omitempty"`
	Linux          *deployLinux   `json:"linux,omitempty"`
}

// dockerBuildExcludeDirs are directory basenames never sent as part of a
// Docker build context — the same version-control/cache junk
// snapshotSource already excludes for the Windows adapter.
var dockerBuildExcludeDirs = map[string]bool{
	".git": true, ".hg": true, ".svn": true, "__pycache__": true,
	"node_modules": true, ".pytest_cache": true, ".mypy_cache": true,
}

// deployStepOrder is the fixed pipeline every deploy_release result
// describes, in order, whatever happens along the way.
var deployStepOrder = []string{
	"snapshot", "shared_dirs", "venv", "pip_install", "django_check", "migrate", "collectstatic",
}

// defaultExcludes are directory basenames never copied into a release
// snapshot: version control metadata, build/test caches, and any virtual
// environment from the developer's own machine (which would be broken
// anyway — a venv hardcodes absolute interpreter paths).
var defaultExcludes = []string{
	".git", ".hg", ".svn", "__pycache__", ".venv", "venv", "env",
	"node_modules", ".pytest_cache", ".mypy_cache",
}

// HandleDeployRelease materializes one immutable release of a Django
// application on this server: a clean snapshot of the source, junctions to
// per-application shared storage, a dedicated virtualenv, and Django's own
// check/migrate/collectstatic.
//
// A step failing mid-pipeline is NOT a Go error: the handler returns a
// normal result with "ok": false and a step-by-step account of what ran,
// what failed, and what was therefore skipped — core.Agent only sends a
// result when the handler returns nil, so returning an error here would
// throw away exactly the detail an operator needs. A Go error is reserved
// for structurally broken input the pipeline can't even be described for.
func HandleDeployRelease(ctx context.Context, raw json.RawMessage) (map[string]any, error) {
	var payload deployReleasePayload
	if err := json.Unmarshal(raw, &payload); err != nil {
		return nil, fmt.Errorf("invalid deploy_release payload: %w", err)
	}
	if err := validateDeployPayload(payload); err != nil {
		return nil, err
	}
	if payload.Operation == "cleanup_image" {
		return cleanupLinuxImage(ctx, payload)
	}

	if payload.Adapter == "linux-docker" {
		return deployLinuxRelease(ctx, payload)
	}
	return deployWindowsRelease(ctx, payload)
}

// deployWindowsRelease is Phase 7's original deploy_release pipeline,
// unchanged — a clean source snapshot, a dedicated virtualenv, and Django's
// own check/migrate/collectstatic.
func deployWindowsRelease(ctx context.Context, payload deployReleasePayload) (map[string]any, error) {
	runner := &stepRunner{}

	// Only folder sources are implemented. A git source is reported as a
	// failed first step rather than a protocol error so the Control Plane
	// renders it like any other deployment failure.
	if payload.Source.Type == "git" {
		runner.run("snapshot", func() (string, error) {
			return "", errors.New("git sources are not yet implemented by this agent version")
		})
		for _, name := range deployStepOrder[1:] {
			runner.skip(name, skippedMessage)
		}
		return map[string]any{"ok": false, "steps": runner.steps}, nil
	}

	w := payload.Windows
	appDir := filepath.Join(config.DefaultDataDir(), "apps", payload.AppSlug)
	releaseDir := filepath.Join(appDir, "releases", payload.ReleaseVersion)
	venvPython := filepath.Join(releaseDir, ".venv", "Scripts", "python.exe")

	runner.run("snapshot", func() (string, error) {
		if err := os.MkdirAll(releaseDir, 0o750); err != nil {
			return "", fmt.Errorf("create release directory %s: %w", releaseDir, err)
		}
		files, dirs, err := snapshotSource(ctx, payload.Source.Location, releaseDir, w)
		if err != nil {
			return "", err
		}
		return fmt.Sprintf("copied %d files, excluded %d directories", files, dirs), nil
	})

	runner.run("shared_dirs", func() (string, error) {
		return linkSharedDirs(appDir, releaseDir, w)
	})

	runner.run("venv", func() (string, error) {
		output, err := runCommand(ctx, "", w.PythonExecutable, "-m", "venv", filepath.Join(releaseDir, ".venv"))
		if err != nil {
			return "", fmt.Errorf("creating the virtual environment failed: %v: %s", err, truncateTail(output))
		}
		return "created virtual environment", nil
	})

	runner.run("pip_install", func() (string, error) {
		requirements := filepath.Join(releaseDir, w.RequirementsFile)
		output, err := runCommand(ctx, "", venvPython,
			"-m", "pip", "install", "--disable-pip-version-check", "--no-input", "-r", requirements)
		if err != nil {
			return "", fmt.Errorf("pip install failed: %v: %s", err, truncateTail(output))
		}
		return fmt.Sprintf("installed requirements (last output: %s)", truncateTail(output)), nil
	})

	runner.run("django_check", func() (string, error) {
		// No DJANGO_SETTINGS_MODULE is set here on purpose: manage.py's own
		// standard os.environ.setdefault boilerplate owns that, and running
		// from releaseDir is what makes the project importable.
		output, err := runCommand(ctx, releaseDir, venvPython, filepath.Join(releaseDir, w.ManagePy), "check")
		if err != nil {
			return "", fmt.Errorf("django check failed: %v: %s", err, truncateTail(output))
		}
		return truncateTail(output), nil
	})

	runner.run("migrate", func() (string, error) {
		release, err := acquireDeployLock(ctx, filepath.Join(appDir, "deploy.lock"))
		if err != nil {
			return "", err
		}
		// Released even if migrate itself fails: a crashed migration must
		// never wedge every future deployment of this application.
		defer release()

		output, err := runCommand(ctx, releaseDir, venvPython, filepath.Join(releaseDir, w.ManagePy), "migrate", "--noinput")
		if err != nil {
			return "", fmt.Errorf("migrate failed: %v: %s", err, truncateTail(output))
		}
		return truncateTail(output), nil
	})

	runner.run("collectstatic", func() (string, error) {
		// Writes through the static junction created in shared_dirs, given
		// the project's own STATIC_ROOT points at BASE_DIR / static_dir.
		output, err := runCommand(ctx, releaseDir, venvPython, filepath.Join(releaseDir, w.ManagePy), "collectstatic", "--noinput")
		if err != nil {
			return "", fmt.Errorf("collectstatic failed: %v: %s", err, truncateTail(output))
		}
		return truncateTail(output), nil
	})

	// Reported as empty only when the release directory was never created:
	// after a failure at, say, collectstatic these paths are real and are
	// exactly what an operator needs to inspect the half-built release.
	result := map[string]any{"ok": runner.ok(), "steps": runner.steps, "release_dir": "", "venv_python": ""}
	if len(runner.steps) > 0 && runner.steps[0].Status == StepSucceeded {
		result["release_dir"] = releaseDir
		result["venv_python"] = venvPython
	}
	return result, nil
}

// validateDeployPayload rejects input the pipeline cannot even be described
// for. app_slug and release_version are checked as path segments because
// they are joined into a filesystem path — a slug of "../.." would
// otherwise let the Control Plane (or anything impersonating it) name a
// directory outside the Agent's data directory.
func validateDeployPayload(payload deployReleasePayload) error {
	if err := validPathSegment("app_slug", payload.AppSlug); err != nil {
		return err
	}
	if err := validPathSegment("release_version", payload.ReleaseVersion); err != nil {
		return err
	}
	if payload.Operation != "" && payload.Operation != "cleanup_image" {
		return fmt.Errorf("invalid deploy_release payload: unsupported operation %q", payload.Operation)
	}
	if payload.Operation == "cleanup_image" {
		if payload.Adapter != "linux-docker" || payload.Source.Type != "" || payload.Source.Location != "" {
			return errors.New("invalid cleanup_image payload: only a Linux release tag can be removed")
		}
		if !cleanupSlug.MatchString(payload.AppSlug) || !cleanupVersion.MatchString(payload.ReleaseVersion) {
			return errors.New("invalid cleanup_image payload: unsafe release tag")
		}
		return nil
	}

	if payload.Adapter == "linux-docker" {
		switch payload.Source.Type {
		case "dockerfile", "image":
		default:
			return fmt.Errorf("invalid deploy_release payload: unsupported source type %q for linux-docker", payload.Source.Type)
		}
		if strings.TrimSpace(payload.Source.Location) == "" {
			return errors.New("invalid deploy_release payload: source.location must not be empty")
		}
		if payload.Source.Type == "image" && !validImmutableImageRef(payload.Source.Location) {
			return errors.New("invalid deploy_release payload: image source must include a sha256 digest")
		}
		if payload.Linux == nil {
			return errors.New("invalid deploy_release payload: missing linux config")
		}
		return nil
	}

	switch payload.Source.Type {
	case "folder", "git":
	default:
		return fmt.Errorf("invalid deploy_release payload: unsupported source type %q", payload.Source.Type)
	}
	if payload.Source.Type == "git" {
		return nil // reported as a failed step instead, see HandleDeployRelease
	}
	if strings.TrimSpace(payload.Source.Location) == "" {
		return errors.New("invalid deploy_release payload: source.location must not be empty")
	}
	if payload.Windows == nil {
		return errors.New("invalid deploy_release payload: missing windows config")
	}
	for name, value := range map[string]string{
		"windows.python_executable": payload.Windows.PythonExecutable,
		"windows.requirements_file": payload.Windows.RequirementsFile,
		"windows.manage_py":         payload.Windows.ManagePy,
	} {
		if strings.TrimSpace(value) == "" {
			return fmt.Errorf("invalid deploy_release payload: %s must not be empty", name)
		}
	}
	return nil
}

func cleanupLinuxImage(ctx context.Context, payload deployReleasePayload) (map[string]any, error) {
	tag := fmt.Sprintf("healer-%s:%s", payload.AppSlug, payload.ReleaseVersion)
	runner := &stepRunner{}
	runner.run("image_remove", func() (string, error) {
		if err := dockerengine.New().RemoveImage(ctx, tag); err != nil {
			return "", err
		}
		return "removed unused Healer release image " + tag, nil
	})
	return map[string]any{"ok": runner.ok(), "steps": runner.steps}, nil
}

// deployLinuxRelease builds (from a Dockerfile) or pulls (an immutable
// image reference) this release's container image and tags/records it —
// the Linux-adapter equivalent of deployWindowsRelease's venv+snapshot
// pipeline. start_instance (not this command) actually runs a container
// from the resulting image.
func deployLinuxRelease(ctx context.Context, payload deployReleasePayload) (map[string]any, error) {
	runner := &stepRunner{}
	client := dockerengine.New()
	tag := fmt.Sprintf("healer-%s:%s", payload.AppSlug, payload.ReleaseVersion)
	var imageRef string

	runner.run("docker_check", func() (string, error) {
		pingCtx, cancel := context.WithTimeout(ctx, 5*time.Second)
		defer cancel()
		if err := client.Ping(pingCtx); err != nil {
			return "", fmt.Errorf("docker daemon is not reachable: %w", err)
		}
		return "docker daemon is reachable", nil
	})

	runner.run("build_or_pull", func() (string, error) {
		switch payload.Source.Type {
		case "dockerfile":
			contextDir := payload.Source.Location
			dockerfileRel := "Dockerfile"
			info, err := os.Stat(contextDir)
			if err != nil {
				return "", fmt.Errorf("source.location %s: %w", contextDir, err)
			}
			if !info.IsDir() {
				// location names the Dockerfile itself; the build context
				// is its parent directory.
				dockerfileRel = filepath.Base(contextDir)
				contextDir = filepath.Dir(contextDir)
			}
			if err := client.BuildImage(ctx, contextDir, dockerfileRel, tag, dockerBuildExcludeDirs); err != nil {
				return "", fmt.Errorf("docker build failed: %w", err)
			}
			imageRef = tag
			return fmt.Sprintf("built image %s", tag), nil
		case "image":
			if err := client.PullImage(ctx, payload.Source.Location); err != nil {
				return "", fmt.Errorf("docker pull failed: %w", err)
			}
			imageRef = payload.Source.Location
			return fmt.Sprintf("pulled image %s", imageRef), nil
		default:
			return "", fmt.Errorf("unsupported source type %q for linux-docker", payload.Source.Type)
		}
	})

	result := map[string]any{"ok": runner.ok(), "steps": runner.steps, "image_ref": ""}
	if runner.ok() {
		result["image_ref"] = imageRef
	}
	return result, nil
}

func validPathSegment(name, value string) error {
	if strings.TrimSpace(value) == "" {
		return fmt.Errorf("invalid deploy_release payload: %s must not be empty", name)
	}
	if value == "." || value == ".." ||
		strings.ContainsAny(value, `/\`) || strings.Contains(value, "..") ||
		filepath.IsAbs(value) {
		return fmt.Errorf("invalid deploy_release payload: %s %q is not a safe directory name", name, value)
	}
	return nil
}

// snapshotSource recursively copies src into dst, skipping junk, secrets,
// and the three shared directories (which become junctions in the next
// step). It returns how many files were copied and how many directory
// subtrees were skipped.
func snapshotSource(ctx context.Context, src, dst string, w *deployWindows) (int, int, error) {
	excluded := make(map[string]bool, len(defaultExcludes)+len(w.Exclude))
	for _, name := range defaultExcludes {
		excluded[strings.ToLower(name)] = true
	}
	for _, name := range w.Exclude {
		if trimmed := strings.TrimSpace(name); trimmed != "" {
			excluded[strings.ToLower(trimmed)] = true
		}
	}

	// Matched against the path relative to the source root only: a nested
	// "docs/static" is real project content and must still be copied.
	topLevel := make(map[string]bool, 3)
	for _, rel := range []string{w.StaticDir, w.MediaDir, w.LogDir} {
		if trimmed := strings.TrimSpace(rel); trimmed != "" {
			topLevel[strings.ToLower(filepath.Clean(trimmed))] = true
		}
	}

	var copied, skippedDirs int
	err := filepath.WalkDir(src, func(path string, entry fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if ctx.Err() != nil {
			return ctx.Err()
		}

		rel, relErr := filepath.Rel(src, path)
		if relErr != nil {
			return relErr
		}
		if rel == "." {
			return nil
		}

		base := strings.ToLower(entry.Name())
		isShared := topLevel[strings.ToLower(filepath.Clean(rel))]

		if entry.IsDir() {
			if excluded[base] || isShared {
				skippedDirs++
				return fs.SkipDir
			}
			return os.MkdirAll(filepath.Join(dst, rel), 0o750)
		}

		if excluded[base] || isShared {
			return nil
		}
		// .pyc files are stale build artifacts; a .env is the developer's
		// own secrets, which must never ride along into a release.
		if strings.EqualFold(filepath.Ext(base), ".pyc") || base == ".env" {
			return nil
		}

		if err := copyFile(path, filepath.Join(dst, rel)); err != nil {
			return err
		}
		copied++
		return nil
	})
	if err != nil {
		return copied, skippedDirs, fmt.Errorf("copying %s: %w", src, err)
	}
	return copied, skippedDirs, nil
}

func copyFile(src, dst string) error {
	if err := os.MkdirAll(filepath.Dir(dst), 0o750); err != nil {
		return err
	}
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer in.Close()

	out, err := os.OpenFile(dst, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, 0o640)
	if err != nil {
		return err
	}
	if _, err := io.Copy(out, in); err != nil {
		out.Close()
		return err
	}
	return out.Close()
}

// linkSharedDirs creates the per-application shared storage (idempotent
// across releases) and points this release's static/media/log directories
// at it with directory symlinks, so uploaded media and logs survive a
// release being rolled back or deleted.
func linkSharedDirs(appDir, releaseDir string, w *deployWindows) (string, error) {
	sharedDir := filepath.Join(appDir, "shared")
	links := []struct {
		rel    string
		shared string
	}{
		{w.StaticDir, "static"},
		{w.MediaDir, "media"},
		{w.LogDir, "logs"},
	}

	for _, link := range links {
		target := filepath.Join(sharedDir, link.shared)
		if err := os.MkdirAll(target, 0o750); err != nil {
			return "", fmt.Errorf("create shared directory %s: %w", target, err)
		}
		if strings.TrimSpace(link.rel) == "" {
			continue
		}

		linkPath := filepath.Join(releaseDir, filepath.Clean(link.rel))
		if err := os.MkdirAll(filepath.Dir(linkPath), 0o750); err != nil {
			return "", fmt.Errorf("create %s: %w", filepath.Dir(linkPath), err)
		}
		// A redeployed release version may already hold a link here.
		if err := os.RemoveAll(linkPath); err != nil {
			return "", fmt.Errorf("clear %s: %w", linkPath, err)
		}
		// On Windows this needs SeCreateSymbolicLinkPrivilege, which the
		// Agent has as a LocalSystem service. Surfaced as a step failure
		// with the real error rather than silently copying instead.
		if err := os.Symlink(target, linkPath); err != nil {
			return "", fmt.Errorf("link %s to %s: %w", linkPath, target, err)
		}
	}
	return "linked static, media, logs to shared storage", nil
}

const (
	deployLockRetryEvery = 2 * time.Second
	deployLockTimeout    = 30 * time.Second
)

// acquireDeployLock takes a whole-application exclusive lock for the
// migrate step: two concurrent deployments of the same application running
// `migrate` at once is the one genuinely dangerous overlap. O_CREATE|O_EXCL
// is atomic on both Windows and Linux, so the file's existence is the lock.
func acquireDeployLock(ctx context.Context, path string) (func(), error) {
	if err := os.MkdirAll(filepath.Dir(path), 0o750); err != nil {
		return nil, fmt.Errorf("create %s: %w", filepath.Dir(path), err)
	}

	deadline := time.Now().Add(deployLockTimeout)
	for {
		file, err := os.OpenFile(path, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o600)
		if err == nil {
			file.Close()
			return func() { _ = os.Remove(path) }, nil
		}
		if !os.IsExist(err) {
			return nil, fmt.Errorf("acquire deployment lock %s: %w", path, err)
		}
		if time.Now().After(deadline) {
			return nil, errors.New("another deployment is already in progress for this application")
		}

		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		case <-time.After(deployLockRetryEvery):
		}
	}
}

// runCommand runs one fixed, structured subprocess — never a shell, never a
// command string assembled from Control Plane input — and returns its
// combined output for the step message.
func runCommand(ctx context.Context, dir, name string, args ...string) (string, error) {
	cmd := exec.CommandContext(ctx, name, args...)
	if dir != "" {
		cmd.Dir = dir
	}
	output, err := cmd.CombinedOutput()
	return string(output), err
}
