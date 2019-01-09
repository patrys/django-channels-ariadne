import asyncio
from functools import partial

from ariadne import ResolverMap
from channels.routing import ProtocolTypeRouter, URLRouter
from django.conf.urls import url

from .graphql import GraphQLConsumer

query = ResolverMap("Query")


@query.field("hello")
async def say_hello(root, info):
    await asyncio.sleep(3)
    return "Hello!"


application = ProtocolTypeRouter(
    {
        "http": URLRouter(
            [
                url(
                    r"^graphql/$",
                    partial(GraphQLConsumer, "type Query { hello: String! }", query),
                )
            ]
        )
    }
)

