"""Abstract Storage for Light Requests and Responses."""

from abc import ABC, abstractmethod
from typing import Optional

from eidas_node.models import LightRequest, LightResponse


class LightStorage(ABC):
    """
    Storage for Light Requests and Responses.

    There is no guarantee of thread safety of the implementations,
    so a storage instance should not be shared among individual requests.
    """

    @abstractmethod
    def get_light_request(self, uid: str) -> Optional[LightRequest]:
        """Look up a LightRequest by a unique id."""

    @abstractmethod
    def get_light_response(self, uid: str) -> Optional[LightResponse]:
        """Look up a LightResponse by a unique id."""

    @abstractmethod
    def put_light_request(self, uid: str, request: LightRequest) -> None:
        """Store a LightRequest under a unique id."""

    @abstractmethod
    def put_light_response(self, uid: str, response: LightResponse) -> None:
        """Store a LightRequest under a unique id."""
