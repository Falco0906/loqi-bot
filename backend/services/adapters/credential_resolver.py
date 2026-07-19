from __future__ import annotations

from abc import ABC, abstractmethod

from services.adapters.credentials import CredentialInstance, CredentialReference


class CredentialResolver(ABC):
    """Abstract resolver for supplying credential instances.

    Concrete implementations (SupabaseCredentialResolver,
    VaultCredentialResolver, EnvironmentCredentialResolver, etc.)
    are built in future phases.  The runtime depends on this interface
    only.
    """

    @abstractmethod
    async def resolve(self, reference: CredentialReference) -> CredentialInstance:
        """Resolve a credential reference into a populated credential instance.

        Args:
            reference: Identifies which credential to retrieve.

        Returns:
            A fully populated CredentialInstance.

        Raises:
            CredentialNotFoundError: if the credential does not exist.
        """

    @abstractmethod
    async def validate(self, reference: CredentialReference) -> bool:
        """Check whether a credential reference is resolvable.

        This should perform a lightweight existence check — not
        necessarily a full secret retrieval.

        Returns:
            True if the reference can be resolved, False otherwise.
        """

    @abstractmethod
    async def exists(self, reference: CredentialReference) -> bool:
        """Check whether a credential reference points to stored data.

        Unlike validate(), this checks backend storage without
        returning the credential value.
        """
