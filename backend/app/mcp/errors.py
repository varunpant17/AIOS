class MCPClientError(Exception):
    """Base class for translated MCP transport and protocol errors."""


class MCPConnectionFailure(MCPClientError):
    pass


class MCPDiscoveryFailure(MCPClientError):
    pass


class MCPInvocationFailure(MCPClientError):
    pass


class MCPTimeoutFailure(MCPClientError):
    pass


class MCPInvalidResponseFailure(MCPClientError):
    pass
