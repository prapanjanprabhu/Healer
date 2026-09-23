package dispatcher

import "strings"

// Step is one stage of a multi-stage command (deploy_release,
// start_instance, stop_instance). It is the pipeline equivalent of
// validate_app's Check: a partial failure is data, not a protocol error, so
// the Control Plane can show an operator exactly how far a deployment got
// and where it stopped.
type Step struct {
	Name    string `json:"name"`
	Status  string `json:"status"`
	Message string `json:"message"`
}

// The only three values Step.Status may take, per the agent protocol.
const (
	StepSucceeded = "succeeded"
	StepFailed    = "failed"
	StepSkipped   = "skipped"
)

const skippedMessage = "skipped after an earlier step failed"

// stepRunner executes a fixed sequence of steps, stopping at the first
// failure but still recording every remaining step as skipped — the result
// always describes the whole pipeline, never a truncated prefix of it.
type stepRunner struct {
	steps  []Step
	failed bool
}

// run executes fn unless an earlier step already failed, in which case the
// step is recorded as skipped and fn never runs. It reports whether the
// pipeline is still healthy, so callers can guard work that happens
// between steps.
func (r *stepRunner) run(name string, fn func() (string, error)) bool {
	if r.failed {
		r.steps = append(r.steps, Step{Name: name, Status: StepSkipped, Message: skippedMessage})
		return false
	}
	message, err := fn()
	if err != nil {
		r.failed = true
		r.steps = append(r.steps, Step{Name: name, Status: StepFailed, Message: err.Error()})
		return false
	}
	r.steps = append(r.steps, Step{Name: name, Status: StepSucceeded, Message: message})
	return true
}

// skip records a step that was deliberately not attempted, without marking
// the pipeline as failed.
func (r *stepRunner) skip(name, message string) {
	r.steps = append(r.steps, Step{Name: name, Status: StepSkipped, Message: message})
}

func (r *stepRunner) ok() bool { return !r.failed }

// maxOutputChars caps how much subprocess output is echoed back to the
// Control Plane in a step message — enough to diagnose a failure (the tail
// is where the traceback and the error line are), bounded so one noisy pip
// install can't flood a WebSocket frame.
const maxOutputChars = 2000

// truncateTail keeps the last maxOutputChars characters of subprocess
// output, which is where Python tracebacks and pip's summary live.
func truncateTail(output string) string {
	trimmed := strings.TrimSpace(output)
	if len(trimmed) <= maxOutputChars {
		return trimmed
	}
	return "...(truncated)... " + trimmed[len(trimmed)-maxOutputChars:]
}
