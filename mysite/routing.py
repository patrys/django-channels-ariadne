from channels.routing import ProtocolTypeRouter, URLRouter
from django.conf.urls import url

from .graphql import create_graphql_consumer


application = ProtocolTypeRouter({
    "http": URLRouter([
        url(r"^graphql/$", create_graphql_consumer("type Query { hello: String! }"))
    ])
})