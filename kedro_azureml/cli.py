import os
from contextlib import contextmanager
from copy import deepcopy
from io import StringIO

import click

from pathlib import Path
from typing import Optional

import yaml

from kedro_azureml.cli_functions import (
    get_context_and_pipeline,
)
from kedro_azureml.client import AzureMLPipelinesClient
from kedro_azureml.config import CONFIG_TEMPLATE
from kedro_azureml.constants import KEDRO_AZURE_BLOB_TEMP_DIR_NAME
from kedro_azureml.generator import AzureMLPipelineGenerator
from kedro_azureml.utils import CliContext, KedroContextManager


@click.group("AzureML")
def commands():
    """Kedro plugin adding support for Azure ML Pipelines"""
    pass


@commands.group(
    name="azureml", context_settings=dict(help_option_names=["-h", "--help"])
)
@click.option(
    "-e",
    "--env",
    "env",
    type=str,
    default=lambda: os.environ.get("KEDRO_ENV", "local"),
    help="Environment to use.",
)
@click.pass_obj
@click.pass_context
def azureml_group(ctx, metadata, env):
    ctx.ensure_object(dict)
    ctx.obj = CliContext(env, metadata)


@azureml_group.command()
@click.argument("resource_group")
@click.argument("workspace_name")
@click.argument("experiment_name")
@click.argument("cluster_name")
@click.argument("storage_account_name")
@click.argument("storage_container")
@click.option("--acr", help="Azure Container Registry repo name", default="")
@click.pass_obj
def init(
    ctx: CliContext,
    resource_group,
    workspace_name,
    experiment_name,
    cluster_name,
    storage_account_name,
    storage_container,
    acr,
):
    with KedroContextManager(ctx.metadata.package_name, ctx.env) as mgr:
        target_path = Path.cwd().joinpath("conf/base/azureml.yml")
        with StringIO() as buffer:
            yaml.safe_dump(CONFIG_TEMPLATE.dict(), buffer)
            cfg = buffer.getvalue().format(
                **{
                    "resource_group": resource_group,
                    "workspace_name": workspace_name,
                    "experiment_name": experiment_name,
                    "cluster_name": cluster_name,
                    "docker_image": (
                        f"{acr}.azurecr.io/{mgr.context.project_path.name}:latest"
                        if acr
                        else "<fill in docker image>"
                    ),
                    "storage_container": storage_container,
                    "storage_account_name": storage_account_name,
                }
            )
            target_path.write_text(cfg)

        click.echo(f"Configuration generated in {target_path}")

        click.echo(
            click.style(
                f"It's recommended to set Lifecycle management rule for storage container {storage_container} "
                f"to avoid costs of long-term storage of the temporary data."
                f"\nTemporary data will be stored under abfs://{storage_container}/{KEDRO_AZURE_BLOB_TEMP_DIR_NAME} path"
                f"\nSee https://docs.microsoft.com/en-us/azure/storage/blobs/lifecycle-management-policy-configure?tabs=azure-portal",  # noqa
                fg="green",
            )
        )

        if not acr:
            click.echo(
                click.style(
                    "Please fill in docker image name before running the pipeline",
                    fg="yellow",
                )
            )


@azureml_group.command()
@click.option(
    "-s",
    "--subscription_id",
    help="Azure Subscription ID. Defaults to env `AZURE_SUBSCRIPTION_ID`",
    default=lambda: os.getenv("AZURE_SUBSCRIPTION_ID", ""),
    type=str,
)
@click.option(
    "-i",
    "--image",
    type=str,
    help="Docker image to use for pipeline execution.",
)
@click.option(
    "-p",
    "--pipeline",
    "pipeline",
    type=str,
    help="Name of pipeline to run",
    default="__default__",
)
@click.option(
    "--param",
    "params",
    type=str,
    multiple=True,
    help="Parameters override in form of `key=value`",
)
@click.option("--wait-for-completion", type=bool, is_flag=True, default=False)
@click.pass_obj
def run(
    ctx: CliContext,
    subscription_id: str,
    image: Optional[str],
    pipeline: str,
    params: list,
    wait_for_completion: bool,
):
    assert subscription_id, "Please provide Azure Subscription ID"
    mgr: KedroContextManager
    with get_context_and_pipeline(ctx, image, pipeline, params) as (mgr, az_pipeline):
        az_client = AzureMLPipelinesClient(az_pipeline, subscription_id)
        az_client.run(mgr.plugin_config.azure, wait_for_completion)


@azureml_group.command()
@click.option(
    "-i",
    "--image",
    type=str,
    help="Docker image to use for pipeline execution.",
)
@click.option(
    "-p",
    "--pipeline",
    "pipeline",
    type=str,
    help="Name of pipeline to run",
    default="__default__",
)
@click.option(
    "--param",
    "params",
    type=str,
    multiple=True,
    help="Parameters override in form of `key=value`",
)
@click.option(
    "-o",
    "--output",
    type=click.types.Path(exists=False, dir_okay=False),
    default="pipeline.yaml",
    help="Pipeline YAML definition file.",
)
@click.pass_obj
def compile(
    ctx: CliContext, image: Optional[str], pipeline: str, params: list, output: str
):
    with get_context_and_pipeline(ctx, image, pipeline, params) as (_, az_pipeline):
        Path(output).write_text(str(az_pipeline))
