import boto3
import os
import json
import time
from botocore.exceptions import ClientError
from typing import List

organizations_client = boto3.client("organizations")
sns_client = boto3.client("sns")


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
        raise ValueError(f"Could not find OU with name: {ou_name}")
    return ou_id


def get_accounts_to_process(graveyard_ou_id: str) -> List[str]:
    """
    Lists all accounts in the organization and returns IDs of closed accounts
    that are not already in the Graveyard OU.
    """
    accounts_to_process = []
    paginator = organizations_client.get_paginator('list_accounts')
    
    try:
        for page in paginator.paginate():
            for account in page['Accounts']:
                if account['Status'] == 'SUSPENDED':
                    current_parent = get_current_parent(account['Id'])
                    
                    if current_parent != graveyard_ou_id:
                        print(f"Found closed account to process: {account['Id']} ({account['Name']})")
                        accounts_to_process.append(account['Id'])
                    else:
                        print(f"Skipping closed account {account['Id']} - already in Graveyard OU")
                        
        print(f"Total accounts to process: {len(accounts_to_process)}")
        return accounts_to_process
    except Exception as e:
        print(f"Error listing accounts: {e}")
        raise


def lambda_handler(event, context):
    """
    AWS Lambda handler that processes account closure events and moves closed accounts to a Graveyard OU.
    """
    try:
        graveyard_ou_id = get_ou_id_by_name(os.environ['GRAVEYARD_OU_NAME'])
        accounts_to_process = get_accounts_to_process(graveyard_ou_id)
        
        if not accounts_to_process:
            print("No closed accounts found that need processing")
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
                        organizations_client.move_account(
                            AccountId=account_id,
                            SourceParentId=get_current_parent(account_id),
                            DestinationParentId=graveyard_ou_id,
                        )
                        print(f"Account {account_id} moved to Graveyard OU: {graveyard_ou_id}")
                        processed_accounts.append(account_id)
                        break
                    except ClientError as ce:
                        if attempt == max_retries - 1:  # Last attempt
                            raise  # Re-raise the last exception
                        
                        delay = base_delay * (2 ** attempt)
                        print(f"Attempt {attempt + 1} failed for account {account_id}. Retrying in {delay} seconds...")
                        time.sleep(delay)
                        
            except Exception as e:
                print(f"Error processing account {account_id}: {e}")
                failed_accounts.append(account_id)
                continue
        
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
        print(f"Error processing account closures: {e}")
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
    response = organizations_client.list_parents(ChildId=account_id)
    if "Parents" in response and len(response["Parents"]) > 0:
        return response["Parents"][0]["Id"]
    else:
        raise ValueError(f"Could not find parent for account {account_id}.")
