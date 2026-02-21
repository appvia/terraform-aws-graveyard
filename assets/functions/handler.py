"""
AWS Lambda function to move closed accounts to a "Graveyard" OU in AWS Organizations.

This function is designed to be triggered by an EventBridge rule that listens for 
account closure events. When a closed account is detected, the function checks if the
account is already in the designated "Graveyard" OU. If not, it attempts to move 
the account to the Graveyard OU, implementing retries with exponential backoff to handle 
potential transient errors.
"""

import boto3
import json
import logging
import os
import time
from botocore.exceptions import ClientError
from datetime import datetime, timezone
from typing import Any, List

organizations_client = boto3.client("organizations")
sns_client = boto3.client("sns")

# Default logger for all log messages in this module, configured to emit JSON-formatted logs to stdout.
logger = logging.getLogger(__name__)
# Set the log level from the environment variable (set by Lambda) or default to INFO.
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())


class _JSONFormatter(logging.Formatter):
    """Emit each log record as a single JSON object."""

    # Standard Python logging record fields to exclude from output
    _EXCLUDE_FIELDS = {
        "name",
        "msg",
        "args",
        "created",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "module",
        "msecs",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "thread",
        "threadName",
        "exc_info",
        "exc_text",
        "taskName",
    }

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Include only extra fields (exclude standard logging record attributes)
        for key, value in record.__dict__.items():
            if key not in self._EXCLUDE_FIELDS:
                log_entry[key] = value

        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry, default=str)


_handler = logging.StreamHandler()
_handler.setFormatter(_JSONFormatter())
logger.handlers = [_handler]
logger.propagate = False


def get_ou_id_by_name(ou_name):
    """
    Find an Organizational Unit ID by its name by recursively searching through the AWS organization.

    Args:
        ou_name (str): The name of the Organizational Unit to find

    Returns:
        str: The ID of the found Organizational Unit

    Raises:
        ValueError: If no OU with the specified name is found
    """

    logger.info(
        "Searching for organizational unit by name",
        extra={
            "action": "get_ou_id_by_name",
            "ou_name": ou_name,
        },
    )

    root_id = organizations_client.list_roots()["Roots"][0]["Id"]

    def search_ou(parent_id):
        paginator = organizations_client.get_paginator(
            "list_organizational_units_for_parent"
        )
        for page in paginator.paginate(ParentId=parent_id):
            for ou in page["OrganizationalUnits"]:
                if ou["Name"] == ou_name:
                    return ou["Id"]
                # Recursively search in this OU
                child_ou_id = search_ou(ou["Id"])
                if child_ou_id:
                    return child_ou_id
        return None

    ou_id = search_ou(root_id)
    if not ou_id:
        logger.error(
            "Organizational unit not found",
            extra={
                "action": "get_ou_id_by_name",
                "ou_name": ou_name,
            },
        )
        raise ValueError(f"Could not find OU with name: {ou_name}")

    logger.debug(
        "Found organizational unit",
        extra={
            "action": "get_ou_id_by_name",
            "ou_name": ou_name,
            "ou_id": ou_id,
        },
    )
    
    return ou_id


def get_accounts_to_process(graveyard_ou_id: str) -> List[str]:
    """
    Lists all accounts in the organization and returns IDs of closed accounts
    that are not already in the Graveyard OU.
    """

    logger.info(
        "Starting scan for closed accounts",
        extra={
            "action": "get_accounts_to_process",
            "graveyard_ou_id": graveyard_ou_id,
        },
    )

    accounts_to_process = []
    paginator = organizations_client.get_paginator('list_accounts')
    
    try:
        for page in paginator.paginate():
            for account in page['Accounts']:
                if account['Status'] == 'SUSPENDED':
                    current_parent = get_current_parent(account['Id'])
                    
                    if current_parent != graveyard_ou_id:
                        logger.info(
                            "Found closed account to process",
                            extra={
                                "action": "get_accounts_to_process",
                                "account_id": account['Id'],
                                "account_name": account['Name'],
                                "current_parent": current_parent,
                            },
                        )
                        accounts_to_process.append(account['Id'])
                    else:
                        logger.debug(
                            "Skipping closed account already in Graveyard OU",
                            extra={
                                "action": "get_accounts_to_process",
                                "account_id": account['Id'],
                                "account_name": account['Name'],
                            },
                        )
                        
        logger.info(
            "Completed scan for closed accounts",
            extra={
                "action": "get_accounts_to_process",
                "total_accounts_to_process": len(accounts_to_process),
            },
        )
        return accounts_to_process
    except Exception as e:
        logger.error(
            "Error listing accounts",
            extra={
                "action": "get_accounts_to_process",
                "error": str(e),
            },
        )
        raise


def lambda_handler(event, context):
    """
    AWS Lambda handler that processes account closure events and moves closed accounts to a Graveyard OU.
    """

    logger.info(
        "Processing account closure event",
        extra={
            "action": "lambda_handler",
            "request_id": context.request_id,
        },
    )

    try:
        graveyard_ou_id = get_ou_id_by_name(os.environ['GRAVEYARD_OU_NAME'])
        accounts_to_process = get_accounts_to_process(graveyard_ou_id)
        
        if not accounts_to_process:
            logger.info(
                "No closed accounts found for processing",
                extra={
                    "action": "lambda_handler",
                    "request_id": context.request_id,
                },
            )
            return {
                'statusCode': 200,
                'body': 'No closed accounts found to process'
            }
        
        processed_accounts = []
        failed_accounts = []
        
        # Process each closed account
        for account_id in accounts_to_process:
            try:
                # Move Account to Graveyard OU with retries
                max_retries = 3
                base_delay = 1
                
                for attempt in range(max_retries):
                    try:
                        logger.debug(
                            "Attempting to move account to Graveyard OU",
                            extra={
                                "action": "lambda_handler",
                                "account_id": account_id,
                                "attempt": attempt + 1,
                                "max_retries": max_retries,
                            },
                        )

                        organizations_client.move_account(
                            AccountId=account_id,
                            SourceParentId=get_current_parent(account_id),
                            DestinationParentId=graveyard_ou_id,
                        )

                        logger.info(
                            "Account moved to Graveyard OU",
                            extra={
                                "action": "lambda_handler",
                                "account_id": account_id,
                                "graveyard_ou_id": graveyard_ou_id,
                            },
                        )
                        processed_accounts.append(account_id)
                        break
                    except ClientError as ce:
                        if attempt == max_retries - 1:  # Last attempt
                            raise  # Re-raise the last exception
                        
                        delay = base_delay * (2 ** attempt)
                        logger.warning(
                            "Attempt failed, retrying with exponential backoff",
                            extra={
                                "action": "lambda_handler",
                                "account_id": account_id,
                                "attempt": attempt + 1,
                                "retry_delay_seconds": delay,
                                "error": str(ce),
                            },
                        )
                        time.sleep(delay)
                        
            except Exception as e:
                logger.error(
                    "Error processing account",
                    extra={
                        "action": "lambda_handler",
                        "account_id": account_id,
                        "error": str(e),
                    },
                )
                failed_accounts.append(account_id)
                continue
        
        logger.info(
            "Account closure processing completed",
            extra={
                "action": "lambda_handler",
                "request_id": context.request_id,
                "total_processed": len(processed_accounts),
                "total_failed": len(failed_accounts),
                "processed_accounts": processed_accounts,
                "failed_accounts": failed_accounts,
            },
        )

        return {
            'statusCode': 200,
            'body': {
                'processed_accounts': processed_accounts,
                'failed_accounts': failed_accounts,
                'total_processed': len(processed_accounts),
                'total_failed': len(failed_accounts)
            }
        }

    except Exception as e:
        logger.error(
            "Error processing account closures",
            extra={
                "action": "lambda_handler",
                "request_id": context.request_id,
                "error": str(e),
            },
        )
        raise


def get_current_parent(account_id):
    """
    Retrieve the parent ID of an AWS account.

    Args:
        account_id (str): The ID of the AWS account

    Returns:
        str: The ID of the parent Organizational Unit or root

    Raises:
        ValueError: If the parent cannot be found for the account
    """

    logger.debug(
        "Retrieving parent organizational unit for account",
        extra={
            "action": "get_current_parent",
            "account_id": account_id,
        },
    )

    response = organizations_client.list_parents(ChildId=account_id)
    
    if "Parents" in response and len(response["Parents"]) > 0:
        parent_id = response["Parents"][0]["Id"]
        logger.debug(
            "Found parent organizational unit for account",
            extra={
                "action": "get_current_parent",
                "account_id": account_id,
                "parent_id": parent_id,
            },
        )
        return parent_id
    else:
        logger.error(
            "Parent organizational unit not found for account",
            extra={
                "action": "get_current_parent",
                "account_id": account_id,
            },
        )
        raise ValueError(f"Could not find parent for account: {account_id}")
