import json
from typing import Any, Callable, List, Optional, Union

from ariadne.constants import (
    CONTENT_TYPE_JSON,
    CONTENT_TYPE_TEXT_HTML,
    CONTENT_TYPE_TEXT_PLAIN,
    DATA_TYPE_JSON,
    HTTP_STATUS_200_OK,
    HTTP_STATUS_400_BAD_REQUEST,
    PLAYGROUND_HTML,
)
from ariadne.exceptions import HttpBadRequestError, HttpError, HttpMethodNotAllowedError
from ariadne.executable_schema import make_executable_schema
from ariadne.types import Bindable
from channels.generic.http import AsyncHttpConsumer
from graphql import GraphQLError, format_error, graphql
from graphql.execution import ExecutionResult
import traceback


class GraphQLConsumer(AsyncHttpConsumer):
    def __init__(
        self,
        type_defs: Union[str, List[str]],
        resolvers: Union[Bindable, List[Bindable], None] = None,
        *args,
        **kwargs
    ):
        self.schema = make_executable_schema(type_defs, resolvers)
        return super().__init__(*args, **kwargs)

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
        print("REQUEST", self.scope)
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
