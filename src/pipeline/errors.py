class PipelineError(Exception):
    """Error esperado que la CLI muestra sin traza. Su mensaje nunca incluye claves."""


class ConfigError(PipelineError):
    pass


class DatabaseError(PipelineError):
    pass


class KeystoreError(PipelineError):
    pass
