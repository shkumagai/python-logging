# Copyright 2016 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Wrapper for adapting the autogenerated gapic client to the hand-written
client."""

from google.cloud.logging_v2.services.config_service_v2 import ConfigServiceV2Client
from google.cloud.logging_v2.services.logging_service_v2 import LoggingServiceV2Client
from google.cloud.logging_v2.services.metrics_service_v2 import MetricsServiceV2Client
from google.cloud.logging_v2.types import CreateSinkRequest
from google.cloud.logging_v2.types import UpdateSinkRequest
from google.cloud.logging_v2.types import ListSinksRequest
from google.cloud.logging_v2.types import ListLogMetricsRequest
from google.cloud.logging_v2.types import ListLogEntriesRequest
from google.cloud.logging_v2.types import WriteLogEntriesRequest
from google.cloud.logging_v2.types import LogSink
from google.cloud.logging_v2.types import LogMetric
from google.cloud.logging_v2.types import LogEntry as LogEntryPB

from google.protobuf.json_format import MessageToDict
from google.protobuf.json_format import ParseDict

from google.cloud.logging_v2._helpers import entry_from_resource
from google.cloud.logging_v2.sink import Sink
from google.cloud.logging_v2.metric import Metric

from google.api_core import client_info
from google.api_core import gapic_v1


class _LoggingAPI(object):
    """Helper mapping logging-related APIs."""

    def __init__(self, gapic_api, client):
        self._gapic_api = gapic_api
        self._client = client

    def list_entries(
        self,
        resource_names,
        *,
        filter_=None,
        order_by=None,
        max_results=None,
        page_size=None,
        page_token=None,
    ):
        """Return a generator of log entry resources.

        Args:
            resource_names (Sequence[str]): Names of one or more parent resources
                from which to retrieve log entries:

                ::

                    "projects/[PROJECT_ID]"
                    "organizations/[ORGANIZATION_ID]"
                    "billingAccounts/[BILLING_ACCOUNT_ID]"
                    "folders/[FOLDER_ID]"

            filter_ (str): a filter expression. See
                https://cloud.google.com/logging/docs/view/advanced_filters
            order_by (str) One of :data:`~logging_v2.ASCENDING`
                or :data:`~logging_v2.DESCENDING`.
            max_results (Optional[int]):
                Optional. The maximum number of entries to return.
                Non-positive values are treated as 0. If None, uses API defaults.
            page_size (int): number of entries to fetch in each API call. Although
                requests are paged internally, logs are returned by the generator
                one at a time. If not passed, defaults to a value set by the API.
            page_token (str): opaque marker for the starting "page" of entries. If not
                passed, the API will return the first page of entries.
        Returns:
            Generator[~logging_v2.LogEntry]
        """
        # full resource names are expected by the API
        resource_names = resource_names
        request = ListLogEntriesRequest(
            resource_names=resource_names,
            filter=filter_,
            order_by=order_by,
            page_size=page_size,
            page_token=page_token,
        )

        response = self._gapic_api.list_log_entries(request=request)
        log_iter = iter(response)

        # We attach a mutable loggers dictionary so that as Logger
        # objects are created by entry_from_resource, they can be
        # re-used by other log entries from the same logger.
        loggers = {}

        if max_results is not None and max_results < 0:
            raise ValueError("max_results must be positive")

        # create generator
        def log_entries_pager(log_iter):
            i = 0
            for entry in log_iter:
                if max_results is not None and i >= max_results:
                    break
                log_entry_dict = _parse_log_entry(LogEntryPB.pb(entry))
                yield entry_from_resource(log_entry_dict, self._client, loggers=loggers)
                i += 1

        return log_entries_pager(log_iter)

    def write_entries(
        self,
        entries,
        *,
        logger_name=None,
        resource=None,
        labels=None,
        partial_success=True,
        dry_run=False,
    ):
        """Log an entry resource via a POST request

        Args:
            entries (Sequence[Mapping[str, ...]]): sequence of mappings representing
                the log entry resources to log.
            logger_name (Optional[str]): name of default logger to which to log the entries;
                individual entries may override.
            resource(Optional[Mapping[str, ...]]): default resource to associate with entries;
                individual entries may override.
            labels (Optional[Mapping[str, ...]]): default labels to associate with entries;
                individual entries may override.
            partial_success (Optional[bool]): Whether valid entries should be written even if
                some other entries fail due to INVALID_ARGUMENT or
                PERMISSION_DENIED errors. If any entry is not written, then
                the response status is the error associated with one of the
                failed entries and the response includes error details keyed
                by the entries' zero-based index in the ``entries.write``
                method.
            dry_run (Optional[bool]):
                If true, the request should expect normal response,
                but the entries won't be persisted nor exported.
                Useful for checking whether the logging API endpoints are working
                properly before sending valuable data.
        """
        log_entry_pbs = [_log_entry_mapping_to_pb(entry) for entry in entries]

        request = WriteLogEntriesRequest(
            log_name=logger_name,
            resource=resource,
            labels=labels,
            entries=log_entry_pbs,
            partial_success=partial_success,
        )
        self._gapic_api.write_log_entries(request=request)

    def logger_delete(self, logger_name):
        """Delete all entries in a logger.

        Args:
            logger_name (str):  The resource name of the log to delete:

                ::

                    "projects/[PROJECT_ID]/logs/[LOG_ID]"
                    "organizations/[ORGANIZATION_ID]/logs/[LOG_ID]"
                    "billingAccounts/[BILLING_ACCOUNT_ID]/logs/[LOG_ID]"
                    "folders/[FOLDER_ID]/logs/[LOG_ID]"

                ``[LOG_ID]`` must be URL-encoded. For example,
                ``"projects/my-project-id/logs/syslog"``,
                ``"organizations/1234567890/logs/cloudresourcemanager.googleapis.com%2Factivity"``.
        """
        self._gapic_api.delete_log(log_name=logger_name)


class _SinksAPI(object):
    """Helper mapping sink-related APIs."""

    def __init__(self, gapic_api, client):
        self._gapic_api = gapic_api
        self._client = client

    def list_sinks(self, parent, *, max_results=None, page_size=None, page_token=None):
        """List sinks for the parent resource.

        Args:
            parent (str): The parent resource whose sinks are to be listed:

                ::

                    "projects/[PROJECT_ID]"
                    "organizations/[ORGANIZATION_ID]"
                    "billingAccounts/[BILLING_ACCOUNT_ID]"
                    "folders/[FOLDER_ID]".
            max_results (Optional[int]):
                Optional. The maximum number of entries to return.
                Non-positive values are treated as 0. If None, uses API defaults.
            page_size (int): number of entries to fetch in each API call. Although
                requests are paged internally, logs are returned by the generator
                one at a time. If not passed, defaults to a value set by the API.
            page_token (str): opaque marker for the starting "page" of entries. If not
                passed, the API will return the first page of entries.

        Returns:
            Generator[~logging_v2.Sink]
        """
        request = ListSinksRequest(
            parent=parent, page_size=page_size, page_token=page_token
        )
        response = self._gapic_api.list_sinks(request)
        sink_iter = iter(response)

        if max_results is not None and max_results < 0:
            raise ValueError("max_results must be positive")

        def sinks_pager(sink_iter):
            i = 0
            for entry in sink_iter:
                if max_results is not None and i >= max_results:
                    break
                # Convert the GAPIC sink type into the handwritten `Sink` type
                yield Sink.from_api_repr(LogSink.to_dict(entry), client=self._client)
                i += 1

        return sinks_pager(sink_iter)

    def sink_create(
        self, parent, sink_name, filter_, destination, *, unique_writer_identity=False
    ):
        """Create a sink resource.

        See
        https://cloud.google.com/logging/docs/reference/v2/rest/v2/projects.sinks/create

        Args:
            parent(str): The resource in which to create the sink,
                including the parent resource and the sink identifier:

            ::

                "projects/[PROJECT_ID]"
                "organizations/[ORGANIZATION_ID]"
                "billingAccounts/[BILLING_ACCOUNT_ID]"
                "folders/[FOLDER_ID]".
            sink_name (str): The name of the sink.
            filter_ (str): The advanced logs filter expression defining the
                entries exported by the sink.
            destination (str): Destination URI for the entries exported by
                the sink.
            unique_writer_identity (Optional[bool]):  determines the kind of
                IAM identity returned as writer_identity in the new sink.

        Returns:
            dict: The sink resource returned from the API (converted from a
                protobuf to a dictionary).
        """
        sink_pb = LogSink(name=sink_name, filter=filter_, destination=destination)
        request = CreateSinkRequest(
            parent=parent, sink=sink_pb, unique_writer_identity=unique_writer_identity
        )
        created_pb = self._gapic_api.create_sink(request=request)
        return MessageToDict(
            LogSink.pb(created_pb),
            preserving_proto_field_name=False,
            including_default_value_fields=False,
        )

    def sink_get(self, sink_name):
        """Retrieve a sink resource.

        Args:
            sink_name (str): The resource name of the sink,
                including the parent resource and the sink identifier:

            ::

                "projects/[PROJECT_ID]/sinks/[SINK_ID]"
                "organizations/[ORGANIZATION_ID]/sinks/[SINK_ID]"
                "billingAccounts/[BILLING_ACCOUNT_ID]/sinks/[SINK_ID]"
                "folders/[FOLDER_ID]/sinks/[SINK_ID]"

        Returns:
            dict: The sink object returned from the API (converted from a
                protobuf to a dictionary).
        """
        sink_pb = self._gapic_api.get_sink(sink_name=sink_name)
        # NOTE: LogSink message type does not have an ``Any`` field
        #       so `MessageToDict`` can safely be used.
        return MessageToDict(
            LogSink.pb(sink_pb),
            preserving_proto_field_name=False,
            including_default_value_fields=False,
        )

    def sink_update(
        self,
        sink_name,
        filter_,
        destination,
        *,
        unique_writer_identity=False,
    ):
        """Update a sink resource.

        Args:
            sink_name (str): Required. The resource name of the sink,
                including the parent resource and the sink identifier:

            ::

                "projects/[PROJECT_ID]/sinks/[SINK_ID]"
                "organizations/[ORGANIZATION_ID]/sinks/[SINK_ID]"
                "billingAccounts/[BILLING_ACCOUNT_ID]/sinks/[SINK_ID]"
                "folders/[FOLDER_ID]/sinks/[SINK_ID]"
            filter_ (str): The advanced logs filter expression defining the
                entries exported by the sink.
            destination (str): destination URI for the entries exported by
                the sink.
            unique_writer_identity (Optional[bool]): determines the kind of
                IAM identity returned as writer_identity in the new sink.


        Returns:
            dict: The sink resource returned from the API (converted from a
                  protobuf to a dictionary).
        """
        name = sink_name.split("/")[-1]  # parse name out of full resoure name
        sink_pb = LogSink(
            name=name,
            filter=filter_,
            destination=destination,
        )

        request = UpdateSinkRequest(
            sink_name=sink_name,
            sink=sink_pb,
            unique_writer_identity=unique_writer_identity,
        )
        sink_pb = self._gapic_api.update_sink(request=request)
        # NOTE: LogSink message type does not have an ``Any`` field
        #       so `MessageToDict`` can safely be used.
        return MessageToDict(
            LogSink.pb(sink_pb),
            preserving_proto_field_name=False,
            including_default_value_fields=False,
        )

    def sink_delete(self, sink_name):
        """Delete a sink resource.

        Args:
            sink_name (str): Required. The full resource name of the sink to delete,
            including the parent resource and the sink identifier:

            ::

                "projects/[PROJECT_ID]/sinks/[SINK_ID]"
                "organizations/[ORGANIZATION_ID]/sinks/[SINK_ID]"
                "billingAccounts/[BILLING_ACCOUNT_ID]/sinks/[SINK_ID]"
                "folders/[FOLDER_ID]/sinks/[SINK_ID]"

            Example: ``"projects/my-project-id/sinks/my-sink-id"``.
        """
        self._gapic_api.delete_sink(sink_name=sink_name)


class _MetricsAPI(object):
    """Helper mapping sink-related APIs."""

    def __init__(self, gapic_api, client):
        self._gapic_api = gapic_api
        self._client = client

    def list_metrics(
        self, project, *, max_results=None, page_size=None, page_token=None
    ):
        """List metrics for the project associated with this client.

        Args:
            project (str): ID of the project whose metrics are to be listed.
            max_results (Optional[int]):
                Optional. The maximum number of entries to return.
                Non-positive values are treated as 0. If None, uses API defaults.
            page_size (int): number of entries to fetch in each API call. Although
                requests are paged internally, logs are returned by the generator
                one at a time. If not passed, defaults to a value set by the API.
            page_token (str): opaque marker for the starting "page" of entries. If not
                passed, the API will return the first page of entries.

        Returns:
            Generator[logging_v2.Metric]
        """
        path = f"projects/{project}"
        request = ListLogMetricsRequest(
            parent=path,
            page_size=page_size,
            page_token=page_token,
        )
        response = self._gapic_api.list_log_metrics(request=request)
        metric_iter = iter(response)

        if max_results is not None and max_results < 0:
            raise ValueError("max_results must be positive")

        def metrics_pager(metric_iter):
            i = 0
            for entry in metric_iter:
                if max_results is not None and i >= max_results:
                    break
                # Convert GAPIC metrics type into handwritten `Metric` type
                yield Metric.from_api_repr(
                    LogMetric.to_dict(entry), client=self._client
                )
                i += 1

        return metrics_pager(metric_iter)

    def metric_create(self, project, metric_name, filter_, description):
        """Create a metric resource.

        See
        https://cloud.google.com/logging/docs/reference/v2/rest/v2/projects.metrics/create

        Args:
            project (str): ID of the project in which to create the metric.
            metric_name (str): The name of the metric
            filter_ (str): The advanced logs filter expression defining the
                entries exported by the metric.
            description (str): description of the metric.
        """
        parent = f"projects/{project}"
        metric_pb = LogMetric(name=metric_name, filter=filter_, description=description)
        self._gapic_api.create_log_metric(parent=parent, metric=metric_pb)

    def metric_get(self, project, metric_name):
        """Retrieve a metric resource.

        Args:
            project (str): ID of the project containing the metric.
            metric_name (str): The name of the metric

        Returns:
            dict: The metric object returned from the API (converted from a
                  protobuf to a dictionary).
        """
        path = f"projects/{project}/metrics/{metric_name}"
        metric_pb = self._gapic_api.get_log_metric(metric_name=path)
        # NOTE: LogMetric message type does not have an ``Any`` field
        #       so `MessageToDict`` can safely be used.
        return MessageToDict(
            LogMetric.pb(metric_pb),
            preserving_proto_field_name=False,
            including_default_value_fields=False,
        )

    def metric_update(
        self,
        project,
        metric_name,
        filter_,
        description,
    ):
        """Update a metric resource.

        Args:
            project (str): ID of the project containing the metric.
            metric_name (str): the name of the metric
            filter_ (str): the advanced logs filter expression defining the
                entries exported by the metric.
            description (str): description of the metric.

        Returns:
            The metric object returned from the API (converted from a
                  protobuf to a dictionary).
        """
        path = f"projects/{project}/metrics/{metric_name}"
        metric_pb = LogMetric(
            name=path,
            filter=filter_,
            description=description,
        )
        metric_pb = self._gapic_api.update_log_metric(
            metric_name=path, metric=metric_pb
        )
        # NOTE: LogMetric message type does not have an ``Any`` field
        #       so `MessageToDict`` can safely be used.
        return MessageToDict(
            LogMetric.pb(metric_pb),
            preserving_proto_field_name=False,
            including_default_value_fields=False,
        )

    def metric_delete(self, project, metric_name):
        """Delete a metric resource.

        Args:
            project (str): ID of the project containing the metric.
            metric_name (str): The name of the metric
        """
        path = f"projects/{project}/metrics/{metric_name}"
        self._gapic_api.delete_log_metric(metric_name=path)


def _parse_log_entry(entry_pb):
    """Special helper to parse ``LogEntry`` protobuf into a dictionary.

    The ``proto_payload`` field in ``LogEntry`` is of type ``Any``. This
    can be problematic if the type URL in the payload isn't in the
    ``google.protobuf`` registry. To help with parsing unregistered types,
    this function will remove ``proto_payload`` before parsing.

    Args:
        entry_pb (LogEntry): Log entry protobuf.

    Returns:
        dict: The parsed log entry. The ``protoPayload`` key may contain
              the raw ``Any`` protobuf from ``entry_pb.proto_payload`` if
              it could not be parsed.
    """
    try:
        return MessageToDict(
            entry_pb,
            preserving_proto_field_name=False,
            including_default_value_fields=False,
        )
    except TypeError:
        if entry_pb.HasField("proto_payload"):
            proto_payload = entry_pb.proto_payload
            entry_pb.ClearField("proto_payload")
            entry_mapping = MessageToDict(
                entry_pb,
                preserving_proto_field_name=False,
                including_default_value_fields=False,
            )
            entry_mapping["protoPayload"] = proto_payload
            return entry_mapping
        else:
            raise


def _log_entry_mapping_to_pb(mapping):
    """Helper for :meth:`write_entries`, et aliae

    Performs "impedance matching" between the protobuf attrs and
    the keys expected in the JSON API.
    """
    entry_pb = LogEntryPB.pb(LogEntryPB())
    # NOTE: We assume ``mapping`` was created in ``Batch.commit``
    #       or ``Logger._make_entry_resource``. In either case, if
    #       the ``protoPayload`` key is present, we assume that the
    #       type URL is registered with ``google.protobuf`` and will
    #       not cause any issues in the JSON->protobuf conversion
    #       of the corresponding ``proto_payload`` in the log entry
    #       (it is an ``Any`` field).
    ParseDict(mapping, entry_pb)
    return LogEntryPB(entry_pb)


def _client_info_to_gapic(input_info):
    """
    Helper function to convert api_core.client_info to
    api_core.gapic_v1.client_info subclass
    """
    return gapic_v1.client_info.ClientInfo(
        python_version=input_info.python_version,
        grpc_version=input_info.grpc_version,
        api_core_version=input_info.api_core_version,
        gapic_version=input_info.gapic_version,
        client_library_version=input_info.client_library_version,
        user_agent=input_info.user_agent,
        rest_version=input_info.rest_version,
    )


def make_logging_api(client):
    """Create an instance of the Logging API adapter.

    Args:
        client (~logging_v2.client.Client): The client
            that holds configuration details.

    Returns:
        _LoggingAPI: A metrics API instance with the proper credentials.
    """
    info = client._client_info
    if isinstance(info, client_info.ClientInfo):
        # convert into gapic-compatible subclass
        info = _client_info_to_gapic(info)

    generated = LoggingServiceV2Client(
        credentials=client._credentials,
        client_info=info,
        client_options=client._client_options,
    )
    return _LoggingAPI(generated, client)


def make_metrics_api(client):
    """Create an instance of the Metrics API adapter.

    Args:
        client (~logging_v2.client.Client): The client
            that holds configuration details.

    Returns:
        _MetricsAPI: A metrics API instance with the proper credentials.
    """
    info = client._client_info
    if isinstance(info, client_info.ClientInfo):
        # convert into gapic-compatible subclass
        info = _client_info_to_gapic(info)

    generated = MetricsServiceV2Client(
        credentials=client._credentials,
        client_info=info,
        client_options=client._client_options,
    )
    return _MetricsAPI(generated, client)


def make_sinks_api(client):
    """Create an instance of the Sinks API adapter.

    Args:
        client (~logging_v2.client.Client): The client
            that holds configuration details.

    Returns:
        _SinksAPI: A metrics API instance with the proper credentials.
    """
    info = client._client_info
    if isinstance(info, client_info.ClientInfo):
        # convert into gapic-compatible subclass
        info = _client_info_to_gapic(info)

    generated = ConfigServiceV2Client(
        credentials=client._credentials,
        client_info=info,
        client_options=client._client_options,
    )
    return _SinksAPI(generated, client)
