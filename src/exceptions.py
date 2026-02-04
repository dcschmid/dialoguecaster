"""Custom exceptions for DialogueCaster application."""


class DialogueCasterError(Exception):
    """Base exception for DialogueCaster application."""
    pass


class ConfigurationError(DialogueCasterError):
    """Raised when there's a configuration problem."""
    pass


class SynthesisError(DialogueCasterError):
    """Raised when audio synthesis fails."""
    pass


class ValidationError(DialogueCasterError):
    """Raised when input validation fails."""
    pass


class FFmpegError(DialogueCasterError):
    """Raised when FFmpeg operations fail."""
    pass


class DependencyError(DialogueCasterError):
    """Raised when required dependencies are missing."""
    pass
