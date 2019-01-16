from typing import Any, AsyncIterator, Callable, Dict, overload

from ariadne import ResolverMap
from graphql import GraphQLSchema

Subscriber = Callable[..., AsyncIterator]


class SubscriptionAwareResolverMap(ResolverMap):
    _subscribers: Dict[str, Subscriber]

    def __init__(self, name: str):
        super().__init__(name)
        self._subscribers = {}

    @overload
    def subscription(self, name: str) -> Callable[[Subscriber], Subscriber]:
        pass  # pragma: no cover

    @overload
    def subscription(  # pylint: disable=function-redefined
        self, name: str, *, subscriber: Subscriber
    ) -> Subscriber:  # pylint: disable=function-redefined
        pass  # pragma: no cover

    def subscription(
        self, name, *, subscriber=None
    ):  # pylint: disable=function-redefined
        if not subscriber:
            return self.create_register_subscriber(name)
        self._subscribers[name] = subscriber
        return subscriber

    def create_register_subscriber(
        self, name: str
    ) -> Callable[[Subscriber], Subscriber]:
        def register_subscriber(f: Subscriber) -> Subscriber:
            self._subscribers[name] = f
            return f

        return register_subscriber

    def bind_to_schema(self, schema: GraphQLSchema) -> None:
        super().bind_to_schema(schema)
        graphql_type = schema.type_map.get(self.name)
        for field, subscriber in self._subscribers.items():
            if field not in graphql_type.fields:
                raise ValueError(
                    "Field %s is not defined on type %s" % (field, self.name)
                )
            graphql_type.fields[field].subscribe = subscriber
