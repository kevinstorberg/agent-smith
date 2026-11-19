class DuplicateProposalError(ValueError):
    """The same change is already pending or was dismissed by the User."""


class ProposalConflictError(RuntimeError):
    """The proposal or reviewed target changed before the decision."""


class ProposalNotFoundError(LookupError):
    pass
