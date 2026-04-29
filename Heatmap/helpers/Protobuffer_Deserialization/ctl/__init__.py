try:
    from .iox.common_pb2 import ProtocolVersion
    __version__ = '0.0.{}'.format(ProtocolVersion.CURRENT_VERSION)
except AttributeError:
    # handle protobuf versions < 3.11
    from .iox import common_pb2  # import ProtocolVersion
    __version__ = '0.0.{}'.format(common_pb2.CURRENT_VERSION)
