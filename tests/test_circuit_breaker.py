from tracker.circuit_breaker import (
    FAILURE_THRESHOLD,
    is_disabled,
    record_failure,
    record_success,
    reset,
)


def make_state():
    return {}


class TestIsDisabled:
    def test_returns_false_for_unknown_topic(self):
        assert is_disabled(make_state(), "My Topic", "grailed") is False

    def test_returns_false_when_not_disabled(self):
        state = {
            "circuit_breakers": {
                "My Topic": {"grailed": {"consecutive_failures": 2, "disabled": False}}
            }
        }
        assert is_disabled(state, "My Topic", "grailed") is False

    def test_returns_true_when_disabled(self):
        state = {
            "circuit_breakers": {
                "My Topic": {"grailed": {"consecutive_failures": 5, "disabled": True}}
            }
        }
        assert is_disabled(state, "My Topic", "grailed") is True


class TestRecordSuccess:
    def test_resets_counter_to_zero(self):
        state = {
            "circuit_breakers": {
                "My Topic": {"grailed": {"consecutive_failures": 3, "disabled": False}}
            }
        }
        record_success(state, "My Topic", "grailed")
        assert state["circuit_breakers"]["My Topic"]["grailed"]["consecutive_failures"] == 0

    def test_creates_entry_if_missing(self):
        state = {}
        record_success(state, "My Topic", "grailed")
        assert state["circuit_breakers"]["My Topic"]["grailed"]["consecutive_failures"] == 0
        assert state["circuit_breakers"]["My Topic"]["grailed"]["disabled"] is False

    def test_does_not_re_enable_disabled_adapter(self):
        """record_success does NOT re-enable a disabled adapter; only reset() does."""
        state = {
            "circuit_breakers": {
                "My Topic": {"grailed": {"consecutive_failures": 5, "disabled": True}}
            }
        }
        record_success(state, "My Topic", "grailed")
        assert state["circuit_breakers"]["My Topic"]["grailed"]["disabled"] is True


class TestRecordFailure:
    def test_increments_counter(self):
        state = {}
        record_failure(state, "My Topic", "grailed")
        assert state["circuit_breakers"]["My Topic"]["grailed"]["consecutive_failures"] == 1

    def test_does_not_disable_before_threshold(self):
        state = {}
        for _ in range(FAILURE_THRESHOLD - 1):
            record_failure(state, "My Topic", "grailed")
        assert state["circuit_breakers"]["My Topic"]["grailed"]["disabled"] is False

    def test_disables_at_threshold(self):
        state = {}
        for _ in range(FAILURE_THRESHOLD):
            record_failure(state, "My Topic", "grailed")
        assert state["circuit_breakers"]["My Topic"]["grailed"]["disabled"] is True

    def test_logs_warning_at_threshold(self, caplog):
        import logging

        state = {}
        with caplog.at_level(logging.WARNING, logger="tracker.circuit_breaker"):
            for _ in range(FAILURE_THRESHOLD):
                record_failure(state, "My Topic", "grailed")
        assert "auto-disabled" in caplog.text.lower()

    def test_counter_does_not_exceed_threshold(self):
        """Calling record_failure beyond the threshold keeps counter at threshold."""
        state = {}
        for _ in range(FAILURE_THRESHOLD + 3):
            record_failure(state, "My Topic", "grailed")
        assert (
            state["circuit_breakers"]["My Topic"]["grailed"]["consecutive_failures"]
            == FAILURE_THRESHOLD
        )


class TestReset:
    def test_re_enables_disabled_adapter(self):
        state = {
            "circuit_breakers": {
                "My Topic": {"grailed": {"consecutive_failures": 5, "disabled": True}}
            }
        }
        reset(state, "My Topic", "grailed")
        assert state["circuit_breakers"]["My Topic"]["grailed"]["disabled"] is False
        assert state["circuit_breakers"]["My Topic"]["grailed"]["consecutive_failures"] == 0

    def test_creates_entry_if_missing(self):
        state = {}
        reset(state, "My Topic", "grailed")
        assert state["circuit_breakers"]["My Topic"]["grailed"]["disabled"] is False
