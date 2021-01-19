"""Sample tap stream test for tap-gitlab."""

import copy
from pathlib import Path
from singer_sdk.typehelpers import (
    ArrayType,
    DateTimeType,
    IntegerType,
    PropertiesList,
    StringType,
)
from singer_sdk import helpers
from singer_sdk.authenticators import SimpleAuthenticator
from typing import Any, Dict, List, cast

from singer_sdk.streams.rest import RESTStream

SCHEMAS_DIR = Path("./singer_sdk/samples/sample_tap_gitlab/schemas")

DEFAULT_URL_BASE = "https://gitlab.com/api/v4"


class GitlabStream(RESTStream):
    """Sample tap test for gitlab."""

    @property
    def url_base(self) -> str:
        """Return the base GitLab URL."""
        return self.config.get("api_url", DEFAULT_URL_BASE)

    @property
    def authenticator(self) -> SimpleAuthenticator:
        """Return an authenticator for REST API requests."""
        http_headers = {"Private-Token": self.config.get("auth_token")}
        if self.config.get("user_agent"):
            http_headers["User-Agent"] = self.config.get("user_agent")
        return SimpleAuthenticator(stream=self, http_headers=http_headers)

    def get_params(self, stream_or_partition_state: dict) -> Dict[str, Any]:
        """Return a dictionary of values to be used in parameterization."""
        result = copy.deepcopy(stream_or_partition_state)
        result.update({"start_date": self.config.get("start_date")})
        return result


class ProjectBasedStream(GitlabStream):
    """Base class for streams that are keys based on project ID."""

    def get_partitions_list(self) -> List[dict]:
        """Return a list of partition key dicts (if applicable), otherwise None."""
        if "{project_id}" in self.path:
            return [
                {"project_id": id} for id in cast(list, self.config.get("project_ids"))
            ]
        if "{group_id}" in self.path:
            return [{"group_id": id} for id in cast(list, self.config.get("group_ids"))]
        raise ValueError(
            "Could not detect partition type for Gitlab stream "
            f"'{self.name}' ({self.path}). "
            "Expected a URL path containing '{project_id}' or '{group_id}'. "
        )


class ProjectsStream(ProjectBasedStream):
    """Gitlab Projects stream."""

    name = "projects"
    path = "/projects/{project_id}?statistics=1"
    primary_keys = ["id"]
    replication_key = None
    schema_filepath = SCHEMAS_DIR / "projects.json"


class ReleasesStream(ProjectBasedStream):
    """Gitlab Releases stream."""

    name = "releases"
    path = "/projects/{project_id}/releases"
    primary_keys = ["project_id", "commit_id", "tag_name"]
    replication_key = None
    schema_filepath = SCHEMAS_DIR / "releases.json"


class IssuesStream(ProjectBasedStream):
    """Gitlab Issues stream."""

    name = "issues"
    path = "/projects/{project_id}/issues?scope=all&updated_after={start_date}"
    primary_keys = ["id"]
    replication_key = None
    schema_filepath = SCHEMAS_DIR / "issues.json"


class CommitsStream(ProjectBasedStream):
    """Gitlab Commits stream."""

    name = "commits"
    path = (
        "/projects/{project_id}/repository/commits?since={start_date}&with_stats=true"
    )
    primary_keys = ["id"]
    replication_key = None
    schema_filepath = SCHEMAS_DIR / "commits.json"


class EpicsStream(ProjectBasedStream):
    """Gitlab Epics stream.

    This class shows an example of inline `schema` declaration rather than referencing
    a raw json input file.
    """

    name = "epics"
    path = "/groups/{group_id}/epics?updated_after={start_date}"
    primary_keys = ["id"]
    replication_key = None
    schema = PropertiesList(
        IntegerType("id"),
        IntegerType("iid"),
        IntegerType("group_id"),
        IntegerType("parent_id", optional=True),
        StringType("title", optional=True),
        StringType("description", optional=True),
        StringType("state", optional=True),
        IntegerType("author_id", optional=True),
        DateTimeType("start_date", optional=True),
        DateTimeType("end_date", optional=True),
        DateTimeType("due_date", optional=True),
        DateTimeType("created_at", optional=True),
        DateTimeType("updated_at", optional=True),
        ArrayType("labels", wrapped_type=StringType),
        IntegerType("upvotes", optional=True),
        IntegerType("downvotes", optional=True),
    ).to_dict()

    # schema_filepath = SCHEMAS_DIR / "epics.json"

    def post_process(self, row: dict, context: dict) -> dict:
        """Perform post processing, including queuing up any child stream types."""
        # Ensure child state record(s) are created
        _ = helpers.get_stream_state_dict(
            self.tap_state,
            "epic_issues",
            partition_keys={"group_id": context["group_id"], "epic_id": row["id"]},
        )
        return super().post_process(row, context)


class EpicIssuesStream(GitlabStream):
    """EpicIssues stream class.

    NOTE: This should only be run after epics have been synced, since epic streams
          have a dependency on the state generated by epics.
    """

    name = "epic_issues"
    path = "/groups/{group_id}/epics/{epic_id}/issues"
    primary_keys = ["id"]
    replication_key = None
    schema_filepath = SCHEMAS_DIR / "epic_issues.json"
    parent_stream_types = [EpicsStream]  # Stream should wait for parents to complete.

    def get_params(self, stream_or_partition_state: dict) -> dict:
        """Return a dictionary of values to be used in parameterization."""
        result = super().get_params(stream_or_partition_state)
        if "epic_id" not in stream_or_partition_state:
            raise ValueError("Cannot sync epic issues without already known epic IDs.")
        return result
