class StageError(Exception):
    """A pipeline stage failed with a machine-readable ``code``."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message
