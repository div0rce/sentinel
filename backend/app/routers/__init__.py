"""FastAPI routers for Sentinel's HTTP surface.

One module per domain. Each router defines its own Pydantic request/response models
inline so changes stay co-located with the endpoint they describe.
"""
