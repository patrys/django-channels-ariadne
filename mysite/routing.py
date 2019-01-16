import asyncio

from ariadne import gql, ResolverMap
from ariadne.executable_schema import make_executable_schema
from channels.routing import ProtocolTypeRouter, URLRouter
from django.conf.urls import url
from graphql.pyutils import EventEmitter, EventEmitterAsyncIterator
from graphql.subscription import subscribe

from .database import db, init_database, Note
from .graphql import GraphQLHTTPConsumer, GraphQLWebsocketConsumer
from .subscription import SubscriptionAwareResolverMap

SCHEMA = gql(
    """
type Note {
    id: ID!
    title: String
    body: String
}

type Query {
    hello: String!
    notes: [Note!]!
    notesContaining(query: String!): [Note!]!
}

type Mutation {
    createNote(title: String!, body: String!): Note!
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


@query.field("notes")
async def get_all_notes(root, info):
    await init_database()  # FIXME: channels needs to expose the ready_callable from daphne
    notes = await Note.query.gino.all()
    return notes


@query.field("notesContaining")
async def get_notes_containing(root, info, query: str):
    await init_database()  # FIXME: channels needs to expose the ready_callable from daphne
    notes = await Note.query.where(Note.title.like("%{}%".format(query))).gino.all()

    return notes


@mutation.field("sendMessage")
async def send_message(root, info, message):
    pubsub.emit("message", message)
    return True


@mutation.field("createNote")
async def create_note(root, info, title: str, body: str):
    await init_database()  # FIXME: channels needs to expose the ready_callable from daphne
    note = await Note.create(title=title, body=body)
    return note


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
