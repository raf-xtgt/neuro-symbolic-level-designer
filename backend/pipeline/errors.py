class StageError(Exception):
    """A pipeline stage failed with a machine-readable ``code``.

    ``details`` (optional) goes into the job summary, for example the last
    validation report of a failed planning run.
    """

    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details
