package dispatcher

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"runtime"
	"testing"

	"github.com/healer-platform/agent/internal/config"
)

func mustJSON(t *testing.T, payload map[string]any) json.RawMessage {
	t.Helper()
	raw, err := json.Marshal(payload)
	if err != nil {
		t.Fatalf("marshal payload: %v", err)
	}
	return raw
}

func stepsOf(t *testing.T, result map[string]any) []Step {
	t.Helper()
	steps, ok := result["steps"].([]Step)
	if !ok {
		t.Fatalf("expected result[\"steps\"] to be []Step, got %T", result["steps"])
	}
	return steps
}

func findStep(t *testing.T, steps []Step, name string) Step {
	t.Helper()
	for _, s := range steps {
		if s.Name == name {
			return s
		}
	}
	t.Fatalf("no step named %q in %+v", name, steps)
	return Step{}
}

// TestHandleDeployReleaseUnsupportedGitSourceIsReportedNotFailed pins the
// contract that an unimplemented source type is *data* — a failed first
// step the Control Plane can render — not a Go error, which core.Agent
// would report without any result payload at all.
func TestHandleDeployReleaseUnsupportedGitSourceIsReportedNotFailed(t *testing.T) {
	result, err := HandleDeployRelease(context.Background(), mustJSON(t, map[string]any{
		"app_slug":        "healer-agent-git-source-test",
		"release_version": "20260923041530",
		"source":          map[string]any{"type": "git", "location": "https://example.invalid/erp.git", "ref": nil},
		"windows": map[string]any{
			"python_executable": "python.exe",
			"requirements_file": "requirements.txt",
			"manage_py":         "manage.py",
		},
	}))
	if err != nil {
		t.Fatalf("a git source must not be reported as a protocol error: %v", err)
	}
	if result["ok"] != false {
		t.Errorf("expected ok=false, got %v", result["ok"])
	}

	steps := stepsOf(t, result)
	if len(steps) != len(deployStepOrder) {
		t.Fatalf("expected all %d steps to be reported, got %d: %+v", len(deployStepOrder), len(steps), steps)
	}
	if steps[0].Name != "snapshot" || steps[0].Status != StepFailed {
		t.Errorf("expected the snapshot step to be reported as failed, got %+v", steps[0])
	}
	if steps[0].Message != "git sources are not yet implemented by this agent version" {
		t.Errorf("unexpected message: %q", steps[0].Message)
	}
	for i, s := range steps[1:] {
		if s.Name != deployStepOrder[i+1] {
			t.Errorf("step %d: expected %q, got %q", i+1, deployStepOrder[i+1], s.Name)
		}
		if s.Status != StepSkipped {
			t.Errorf("expected %q to be skipped after the failure, got %+v", s.Name, s)
		}
	}

	// Nothing may have been created on disk for a source type the Agent
	// cannot handle.
	appDir := filepath.Join(config.DefaultDataDir(), "apps", "healer-agent-git-source-test")
	if _, err := os.Stat(appDir); err == nil {
		os.RemoveAll(appDir)
		t.Errorf("a rejected git deploy must not create %s", appDir)
	}
}

func TestHandleDeployReleaseRejectsStructurallyBrokenPayloads(t *testing.T) {
	t.Run("malformed json", func(t *testing.T) {
		if _, err := HandleDeployRelease(context.Background(), json.RawMessage(`{"app_slug":`)); err == nil {
			t.Error("expected an error for malformed JSON")
		}
	})

	t.Run("empty payload", func(t *testing.T) {
		if _, err := HandleDeployRelease(context.Background(), json.RawMessage(`{}`)); err == nil {
			t.Error("expected an error for a payload with no app_slug")
		}
	})

	t.Run("unknown source type", func(t *testing.T) {
		_, err := HandleDeployRelease(context.Background(), mustJSON(t, map[string]any{
			"app_slug": "erp", "release_version": "1",
			"source": map[string]any{"type": "rsync", "location": "."},
		}))
		if err == nil {
			t.Error("expected an error for an unrecognized source type")
		}
	})

	// app_slug and release_version are joined into a filesystem path, so a
	// traversal attempt must never reach the filesystem at all.
	for _, slug := range []string{"..", "../evil", `..\evil`, "a/b", "C:\\evil"} {
		_, err := HandleDeployRelease(context.Background(), mustJSON(t, map[string]any{
			"app_slug": slug, "release_version": "20260923041530",
			"source":  map[string]any{"type": "folder", "location": t.TempDir()},
			"windows": map[string]any{"python_executable": "python.exe", "requirements_file": "r.txt", "manage_py": "manage.py"},
		}))
		if err == nil {
			t.Errorf("expected app_slug %q to be rejected as an unsafe directory name", slug)
		}
	}
}

// TestSnapshotSourceExcludesJunkAndSecrets covers the exclude rules on a
// real directory tree: built-in junk directories, *.pyc and .env, the three
// shared directories (top level only), and extra basenames from the
// payload.
func TestSnapshotSourceExcludesJunkAndSecrets(t *testing.T) {
	src := t.TempDir()
	dst := t.TempDir()

	write := func(rel, content string) {
		full := filepath.Join(src, rel)
		must(t, os.MkdirAll(filepath.Dir(full), 0o755))
		must(t, os.WriteFile(full, []byte(content), 0o644))
	}

	write("manage.py", "print('hi')")
	write("requirements.txt", "# none")
	write("erp/settings.py", "")
	write("erp/wsgi.py", "")
	write("docs/static/keepme.css", "") // nested, NOT the top-level static dir
	write(".git/config", "")
	write("__pycache__/settings.cpython-312.pyc", "")
	write("erp/stale.pyc", "")
	write(".env", "SECRET_KEY=real-production-secret")
	write("node_modules/left-pad/index.js", "")
	write("static/collected.css", "")
	write("media/upload.png", "")
	write("logs/app.log", "")
	write("notes/todo.txt", "")

	files, dirs, err := snapshotSource(context.Background(), src, dst, &deployWindows{
		StaticDir: "static", MediaDir: "media", LogDir: "logs",
		Exclude: []string{"notes"},
	})
	if err != nil {
		t.Fatalf("snapshotSource: %v", err)
	}

	for _, rel := range []string{"manage.py", "requirements.txt", "erp/settings.py", "erp/wsgi.py", "docs/static/keepme.css"} {
		if _, err := os.Stat(filepath.Join(dst, filepath.FromSlash(rel))); err != nil {
			t.Errorf("expected %s to be copied into the release: %v", rel, err)
		}
	}
	for _, rel := range []string{
		".git", "__pycache__", "node_modules", "static", "media", "logs", "notes",
		".env", "erp/stale.pyc",
	} {
		if _, err := os.Stat(filepath.Join(dst, filepath.FromSlash(rel))); err == nil {
			t.Errorf("%s must not be copied into the release", rel)
		}
	}

	if files != 5 {
		t.Errorf("expected 5 copied files, got %d", files)
	}
	// .git, __pycache__, node_modules, static, media, logs, notes
	if dirs != 7 {
		t.Errorf("expected 7 excluded directories, got %d", dirs)
	}
}

// canCreateSymlink reports whether this process may create a directory
// symlink at all — on Windows that needs SeCreateSymbolicLinkPrivilege.
func canCreateSymlink(t *testing.T) bool {
	t.Helper()
	dir := t.TempDir()
	target := filepath.Join(dir, "target")
	must(t, os.MkdirAll(target, 0o755))
	return os.Symlink(target, filepath.Join(dir, "link")) == nil
}

func TestLinkSharedDirsPointsReleaseAtSharedStorage(t *testing.T) {
	appDir := t.TempDir()
	releaseDir := filepath.Join(appDir, "releases", "20260923041530")
	must(t, os.MkdirAll(releaseDir, 0o755))

	w := &deployWindows{StaticDir: "static", MediaDir: "media", LogDir: "logs"}
	message, err := linkSharedDirs(appDir, releaseDir, w)
	if err != nil {
		// Creating a directory symlink needs SeCreateSymbolicLinkPrivilege,
		// which the Agent has as a LocalSystem service but a test runner may
		// not — an environment limit, not a logic failure.
		t.Skipf("cannot create directory symlinks in this environment: %v", err)
	}
	if message != "linked static, media, logs to shared storage" {
		t.Errorf("unexpected message: %q", message)
	}

	for _, pair := range [][2]string{{"static", "static"}, {"media", "media"}, {"logs", "logs"}} {
		linkPath := filepath.Join(releaseDir, pair[0])
		info, err := os.Lstat(linkPath)
		if err != nil {
			t.Fatalf("expected a link at %s: %v", linkPath, err)
		}
		if info.Mode()&os.ModeSymlink == 0 {
			t.Errorf("%s is not a symlink (mode %v)", linkPath, info.Mode())
		}

		// Written through the link, read back from shared storage: this is
		// what makes media and logs survive a release being deleted.
		must(t, os.WriteFile(filepath.Join(linkPath, "probe.txt"), []byte("ok"), 0o644))
		shared := filepath.Join(appDir, "shared", pair[1], "probe.txt")
		if _, err := os.Stat(shared); err != nil {
			t.Errorf("expected the write through %s to land in %s: %v", linkPath, shared, err)
		}
	}

	// Idempotent: a redeploy of the same version must relink, not fail.
	if _, err := linkSharedDirs(appDir, releaseDir, w); err != nil {
		t.Errorf("expected linkSharedDirs to be idempotent, got %v", err)
	}
}

func TestAcquireDeployLockIsExclusive(t *testing.T) {
	lockPath := filepath.Join(t.TempDir(), "deploy.lock")

	release, err := acquireDeployLock(context.Background(), lockPath)
	if err != nil {
		t.Fatalf("acquireDeployLock: %v", err)
	}
	if _, err := os.Stat(lockPath); err != nil {
		t.Fatalf("expected the lock file to exist: %v", err)
	}

	// A second holder waits rather than proceeding — proven here with an
	// already-cancelled context so the test doesn't sit through the real
	// 30-second retry window.
	cancelled, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := acquireDeployLock(cancelled, lockPath); err == nil {
		t.Error("expected a second deployment to be blocked by the lock")
	}

	release()
	if _, err := os.Stat(lockPath); err == nil {
		t.Error("expected the lock file to be removed on release")
	}

	// Free again for the next deployment.
	release2, err := acquireDeployLock(context.Background(), lockPath)
	if err != nil {
		t.Fatalf("expected the lock to be re-acquirable after release: %v", err)
	}
	release2()
}

// TestHandleDeployReleaseRealPipeline exercises the whole handler against a
// real interpreter, a real venv and real subprocess calls — with a stand-in
// manage.py rather than a real Django project, so no network install is
// needed to prove the pipeline's plumbing.
func TestHandleDeployReleaseRealPipeline(t *testing.T) {
	// The Agent runs under ProgramData in production; tests need a writable
	// equivalent because ordinary CI users cannot create C:\ProgramData\Healer.
	t.Setenv("ProgramData", t.TempDir())
	if runtime.GOOS != "windows" {
		t.Skip("the windows-waitress-service adapter's venv layout (.venv/Scripts) only exists on Windows")
	}
	pythonPath, err := findRealPythonForTest()
	if err != nil {
		t.Skipf("no python interpreter available to build a real virtualenv: %v", err)
	}

	src := t.TempDir()
	must(t, os.WriteFile(filepath.Join(src, "requirements.txt"),
		[]byte("# deliberately no third-party dependencies: this test must not hit the network\n"), 0o644))
	// Stands in for a Django project's manage.py: accepts check/migrate/
	// collectstatic and exits 0, which is all this pipeline requires of it.
	must(t, os.WriteFile(filepath.Join(src, "manage.py"),
		[]byte("import sys\nprint('fake manage.py ran:', ' '.join(sys.argv[1:]))\n"), 0o644))
	must(t, os.MkdirAll(filepath.Join(src, "static"), 0o755))
	must(t, os.WriteFile(filepath.Join(src, "static", "old.css"), []byte(""), 0o644))
	must(t, os.WriteFile(filepath.Join(src, ".env"), []byte("SECRET=nope"), 0o644))

	const slug = "healer-agent-deploy-release-test"
	appDir := filepath.Join(config.DefaultDataDir(), "apps", slug)
	t.Cleanup(func() { _ = os.RemoveAll(appDir) })

	// Creating a directory symlink needs SeCreateSymbolicLinkPrivilege,
	// which the Agent holds as a LocalSystem service but a test runner may
	// not. Rather than skipping the whole pipeline over it, drop the three
	// shared directories from the config (they are optional) so venv,
	// pip_install and the three manage.py steps are still exercised for
	// real — TestLinkSharedDirsPointsReleaseAtSharedStorage is where the
	// junction behaviour itself is proven.
	sharedDirs := canCreateSymlink(t)
	staticDir, mediaDir, logDir := "static", "media", "logs"
	if !sharedDirs {
		t.Log("no symlink privilege here: running the pipeline without shared directory junctions")
		staticDir, mediaDir, logDir = "", "", ""
	}

	result, err := HandleDeployRelease(context.Background(), mustJSON(t, map[string]any{
		"app_slug":        slug,
		"release_version": "20260923041530",
		"source":          map[string]any{"type": "folder", "location": src, "ref": nil},
		"windows": map[string]any{
			"python_executable": pythonPath,
			"requirements_file": "requirements.txt",
			"manage_py":         "manage.py",
			"wsgi_module":       "erp.wsgi",
			"settings_module":   "erp.settings",
			"static_dir":        staticDir,
			"media_dir":         mediaDir,
			"log_dir":           logDir,
			"exclude":           []string{},
		},
	}))
	if err != nil {
		t.Fatalf("a failing step must be reported in the result, never as a Go error: %v", err)
	}
	steps := stepsOf(t, result)

	// Asserted before the environment-gated skips below, so this test still
	// proves the snapshot stage on a machine without symlink privilege.
	releaseDir := filepath.Join(appDir, "releases", "20260923041530")
	if s := findStep(t, steps, "snapshot"); s.Status != StepSucceeded {
		t.Fatalf("expected the snapshot step to succeed, got %+v", s)
	}
	if result["release_dir"] != releaseDir {
		t.Errorf("expected release_dir %q, got %v", releaseDir, result["release_dir"])
	}
	if _, err := os.Stat(filepath.Join(releaseDir, "manage.py")); err != nil {
		t.Errorf("expected manage.py in the release: %v", err)
	}
	if _, err := os.Stat(filepath.Join(releaseDir, ".env")); err == nil {
		t.Error("the source .env must never be copied into a release")
	}
	if sharedDirs {
		if _, err := os.Stat(filepath.Join(releaseDir, "static", "old.css")); err == nil {
			t.Error("the top-level static directory must not be copied into a release")
		}
	}

	// A machine with no working ensurepip can't build a virtualenv at all —
	// an environment limit, not a logic failure, so it's a skip, the same
	// graceful degradation validate_app's tests use for a missing
	// interpreter.
	if s := findStep(t, steps, "venv"); s.Status == StepFailed {
		t.Skipf("cannot create a virtualenv in this environment: %s", s.Message)
	}

	for _, name := range deployStepOrder {
		if s := findStep(t, steps, name); s.Status != StepSucceeded {
			t.Errorf("expected step %q to succeed, got %+v", name, s)
		}
	}
	if result["ok"] != true {
		t.Errorf("expected ok=true, got %v", result["ok"])
	}

	venvPython := filepath.Join(releaseDir, ".venv", "Scripts", "python.exe")
	if result["venv_python"] != venvPython {
		t.Errorf("expected venv_python %q, got %v", venvPython, result["venv_python"])
	}
	if _, err := os.Stat(venvPython); err != nil {
		t.Errorf("expected a real interpreter at %s: %v", venvPython, err)
	}
}
