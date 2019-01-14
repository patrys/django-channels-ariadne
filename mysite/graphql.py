import asyncio
import json
from functools import partial
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional, Union, cast

from ariadne.constants import (
    CONTENT_TYPE_JSON,
    CONTENT_TYPE_TEXT_HTML,
    CONTENT_TYPE_TEXT_PLAIN,
    DATA_TYPE_JSON,
    PLAYGROUND_HTML,
)
from ariadne.exceptions import HttpBadRequestError, HttpError, HttpMethodNotAllowedError
from ariadne.types import Bindable
from channels.generic.http import AsyncHttpConsumer
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from graphql import GraphQLError, GraphQLSchema, format_error, graphql, parse, subscribe
from graphql.execution import ExecutionResult
import traceback


class GraphQLHTTPConsumer(AsyncHttpConsumer):
    def __init__(self, schema: GraphQLSchema, *args, **kwargs):
        self.schema = schema
        return super().__init__(*args, **kwargs)

    @classmethod
    def for_schema(cls, schema: GraphQLSchema):
        return partial(cls, schema)

    async def handle(self, body):
        try:
            await self.handle_request(body)
        except GraphQLError as error:
            await self.handle_graphql_error(error)
        except HttpError as error:
            await self.handle_http_error(error)

    async def handle_graphql_error(self, error: GraphQLError) -> None:
        error_json = {"errors": [{"message": error.message}]}
        await self.send_response(
            200,
            json.dumps(error_json).encode("utf-8"),
            headers=[(b"Content-Type", CONTENT_TYPE_TEXT_PLAIN.encode("utf-8"))],
        )

    async def handle_http_error(self, error: HttpError) -> None:
        response_body = error.message or error.status
        await self.send_response(
            200,
            str(response_body).encode("utf-8"),
            headers=[(b"Content-Type", CONTENT_TYPE_TEXT_PLAIN.encode("utf-8"))],
        )

    async def handle_request(self, body: bytes) -> None:
        if self.scope["method"] == "GET":
            await self.handle_get()
        if self.scope["method"] == "POST":
            await self.handle_post(body)
        raise HttpMethodNotAllowedError()

    async def handle_get(self) -> None:
        await self.send_response(
            200,
            PLAYGROUND_HTML.encode("utf-8"),
            headers=[(b"Content-Type", CONTENT_TYPE_TEXT_HTML.encode("utf-8"))],
        )

    async def handle_post(self, body: bytes) -> None:
        data = self.get_request_data(body)
        self.validate_query(data)
        result = await self.execute_query(data)
        await self.return_response_from_result(result)

    def get_request_data(self, body: bytes) -> dict:
        for header, value in self.scope["headers"]:
            if header == b"content-type" and value == DATA_TYPE_JSON.encode("utf-8"):
                break
        else:
            raise HttpBadRequestError(
                "Posted content must be of type {}".format(DATA_TYPE_JSON)
            )

        data = self.parse_request_body(body)
        if not isinstance(data, dict):
            raise GraphQLError("Valid request body should be a JSON object")

        return data

    def parse_request_body(self, request_body: bytes) -> Any:
        try:
            return json.loads(request_body)
        except ValueError:
            raise HttpBadRequestError("Request body is not a valid JSON")

    def validate_query(self, data: dict) -> None:
        self.validate_query_body(data.get("query"))
        self.validate_variables(data.get("variables"))
        self.validate_operation_name(data.get("operationName"))

    def validate_query_body(self, query) -> None:
        if not query or not isinstance(query, str):
            raise GraphQLError("The query must be a string.")

    def validate_variables(self, variables) -> None:
        if variables is not None and not isinstance(variables, dict):
            raise GraphQLError("Query variables must be a null or an object.")

    def validate_operation_name(self, operation_name) -> None:
        if operation_name is not None and not isinstance(operation_name, str):
            raise GraphQLError('"%s" is not a valid operation name.' % operation_name)

    async def execute_query(self, data: dict) -> ExecutionResult:
        return await graphql(
            self.schema,
            data.get("query"),
            root_value=self.get_query_root(data),
            context_value=self.get_query_context(data),
            variable_values=data.get("variables"),
            operation_name=data.get("operationName"),
        )

    def get_query_root(
        self, request_data: dict  # pylint: disable=unused-argument
    ) -> Any:
        """Override this method in inheriting class to create query root."""
        return None

    def get_query_context(
        self, request_data: dict  # pylint: disable=unused-argument
    ) -> Any:
        """Override this method in inheriting class to create query context."""
        return {"scope": self.scope}

    async def return_response_from_result(self, result: ExecutionResult) -> None:
        response = {"data": result.data}
        if result.errors:
            response["errors"] = [format_error(e) for e in result.errors]
        await self.send_response(
            200,
            json.dumps(response).encode("utf-8"),
            headers=[(b"Content-Type", CONTENT_TYPE_JSON.encode("utf-8"))],
        )


class GraphQLWebsocketConsumer(AsyncJsonWebsocketConsumer):
    def __init__(self, schema: GraphQLSchema, *args, **kwargs):
        self.schema = schema
        self.subscriptions: Dict[str, AsyncGenerator] = {}
        return super().__init__(*args, **kwargs)

    @classmethod
    def for_schema(cls, schema: GraphQLSchema):
        return partial(cls, schema)

    async def connect(self):
        await self.accept("graphql-ws")

    async def receive_json(self, message: dict):
        operation_id = cast(str, message.get("id"))
        message_type = cast(str, message.get("type"))
        payload = cast(dict, message.get("payload"))

        if message_type == "connection_init":
            return await self.subscription_init(operation_id, payload)
        if message_type == "connection_terminate":
            return await self.subscription_terminate(operation_id)
        if message_type == "start":
            await self.validate_payload(operation_id, payload)
            return await self.subscription_start(operation_id, payload)
        if message_type == "stop":
            return await self.subscription_stop(operation_id)
        return await self.send_error(operation_id, "Unknown message type")

    async def validate_payload(self, operation_id: str, payload: dict) -> None:
        if not isinstance(payload, dict):
            return await self.send_error(operation_id, "Payload must be an object")
        query = payload.get("query")
        if not query or not isinstance(query, str):
            return await self.send_error(operation_id, "The query must be a string.")
        variables = payload.get("variables")
        if variables is not None and not isinstance(variables, dict):
            return await self.send_error(
                operation_id, "Query variables must be a null or an object."
            )
        operation_name = payload.get("operationName")
        if operation_name is not None and not isinstance(operation_name, str):
            return await self.send_error(
                operation_id, '"%s" is not a valid operation name.' % operation_name
            )

    async def send_message(
        self, operation_id: str, message_type: str, payload: dict = None
    ) -> None:
        message: Dict[str, Any] = {"type": message_type}
        if operation_id is not None:
            message["id"] = operation_id
        if payload is not None:
            message["payload"] = payload
        return await self.send_json(message)

    async def send_result(self, operation_id: str, result: ExecutionResult) -> None:
        payload = {}
        if result.data:
            payload["data"] = result.data
        if result.errors:
            payload["errors"] = [format_error(e) for e in result.errors]
        await self.send_message(operation_id, "data", payload)

    async def send_error(self, operation_id: str, message: str) -> None:
        payload = {"message": message}
        await self.send_message(operation_id, "error", payload)

    async def subscription_init(self, operation_id: str, payload: dict) -> None:
        await self.send_message(operation_id, "ack")

    async def subscription_start(self, operation_id: str, payload: dict) -> None:
        results = await subscribe(
            self.schema,
            parse(payload["query"]),
            root_value=self.get_query_root(payload),
            context_value=self.get_query_context(payload),
            variable_values=payload.get("variables"),
            operation_name=payload.get("operationName"),
        )
        if isinstance(results, ExecutionResult):
            await self.send_result(operation_id, results)
            await self.send_message(operation_id, "complete")
        else:
            asyncio.ensure_future(self.observe(operation_id, results))

    async def subscription_stop(self, operation_id: str) -> None:
        if operation_id in self.subscriptions:
            await self.subscriptions[operation_id].aclose()
            del self.subscriptions[operation_id]

    def get_query_root(
        self, request_data: dict  # pylint: disable=unused-argument
    ) -> Any:
        """Override this method in inheriting class to create query root."""
        return None

    def get_query_context(
        self, request_data: dict  # pylint: disable=unused-argument
    ) -> Any:
        """Override this method in inheriting class to create query context."""
        return {"scope": self.scope}

    async def observe(self, operation_id: str, results: AsyncGenerator) -> None:
        self.subscriptions[operation_id] = results
        async for result in results:
            await self.send_result(operation_id, result)
        await self.send_message(operation_id, "complete", None)

    async def disconnect(self, code: Any) -> None:
        for operation_id in self.subscriptions:
            self.subscription_stop(operation_id)
