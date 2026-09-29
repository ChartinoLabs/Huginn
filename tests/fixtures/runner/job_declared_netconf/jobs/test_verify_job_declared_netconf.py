"""Fixture job that declares NETCONF broker requirements."""

from huginn import Context, ResultStatus, TestCase
from huginn.enums import BrokerType


class VerifyJobDeclaredNetconf(TestCase):
    """Exercise job-declared broker requirements in runner validation."""

    required_brokers = {BrokerType.NETCONF}

    async def setup(self, context: Context) -> None:
        """No-op setup."""
        return None

    async def test(self, context: Context) -> None:
        """Use declared NETCONF broker to perform a GET operation."""
        result = await context.broker.for_protocol("netconf").get(
            context.targets[0],
            "/interfaces",
        )
        context.results.add_result(ResultStatus.PASSED, result.output)

    async def cleanup(self, context: Context) -> None:
        """No-op cleanup."""
        return None
