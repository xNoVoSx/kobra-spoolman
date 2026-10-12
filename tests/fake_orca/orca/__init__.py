"""Minimal stand-in for Orca's Python module 'orca', so the plugin can be imported without Orca."""
import types


class base:  # noqa: N801
    def register_capabilities(self):
        pass


_caps = []


def plugin(cls):
    return cls


def register_capability(cls):
    _caps.append(cls)


class ExecutionResult:
    def __init__(self, message=""):
        self.message = message

    @staticmethod
    def success(message="", data=""):
        return ExecutionResult(message)


class _Cap:
    def get_config(self):
        return "{}"


script = types.SimpleNamespace(ScriptPluginCapabilityBase=_Cap)


class LifecycleEvent:
    PresetSaved = "PresetSaved"
    SlicingJobComplete = "SlicingJobComplete"


class LifecycleEvtCode:
    Ok = "Ok"
    Error = "Error"
    Warn = "Warn"


host = types.SimpleNamespace(preset_bundle=None, ui=None)
