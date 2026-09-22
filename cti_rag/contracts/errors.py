class ContractError(ValueError):
    pass
class ValidationError(ContractError):
    pass
class IdentityError(ContractError):
    pass
class UnknownDiscriminatorError(ValidationError):
    pass
