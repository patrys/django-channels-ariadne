import asyncio

from ariadne import gql, ResolverMap
from ariadne.executable_schema import make_executable_schema
from channels.routing import ProtocolTypeRouter, URLRouter
from django.conf.urls import url
from graphql.pyutils import EventEmitter, EventEmitterAsyncIterator
from graphql.subscription import subscribe

from .graphql import GraphQLHTTPConsumer, GraphQLWebsocketConsumer
from .subscription import SubscriptionAwareResolverMap

SCHEMA = gql(
    """
type Query {
    hello: String!
}

type Mutation {
    sendMessage(message: String!): Boolean!
}

type Subscription {
    messages: String!
}
"""
)
mutation = ResolverMap("Mutation")
pubsub = EventEmitter()
query = ResolverMap("Query")
subscription = SubscriptionAwareResolverMap("Subscription")


@query.field("hello")
async def say_hello(root, info):
    await asyncio.sleep(3)
    return "Hello!"


@mutation.field("sendMessage")
async def send_message(root, info, message):
    pubsub.emit("message", message)
    return True


@subscription.subscription("messages")
def subscribe_messages(root, info):
    return EventEmitterAsyncIterator(pubsub, "message")


@subscription.field("messages")
def push_message(message, info):
    return message


schema = make_executable_schema(SCHEMA, [mutation, query, subscription])


application = ProtocolTypeRouter(
    {
        "http": URLRouter([url(r"^graphql/$", GraphQLHTTPConsumer.for_schema(schema))]),
        "websocket": URLRouter(
            [url(r"^graphql/$", GraphQLWebsocketConsumer.for_schema(schema))]
        ),
    }
)

