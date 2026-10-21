class PluginError(Exception):
    """CLI가 JSON으로 변환할 수 있는, 코드가 붙은 실패."""

    def __init__(self, code, message, hint=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint

    def to_dict(self):
        out = {"ok": False, "code": self.code, "message": self.message}
        if self.hint:
            out["hint"] = self.hint
        return out
