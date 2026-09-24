from digital_estate_manager.models import (
    Asset,
    AssetInfo,
    SubscriptionAssetInfo,
    FinancialAssetInfo,
    CloudStorageAssetInfo,
    SocialMediaAssetInfo,
    GenericAssetInfo,
    DeathPolicy,
    CancelPolicy,
)
from digital_estate_manager.vault import get_default_assets, calculate_metrics
from digital_estate_manager.policies import generate_action_email, get_policies_for_service


def test_asset_info_polymorphism():
    sub = SubscriptionAssetInfo(cost_monthly=12.99, plan_tier="Gold", billing_cycle="monthly")
    assert sub.get_monthly_cost() == 12.99
    assert sub.get_cost_display() == "$12.99/mo"
    assert sub.display_details()["Plan Tier"] == "Gold"

    fin = FinancialAssetInfo(approximate_balance=50000.0, institution_type="crypto_exchange")
    assert fin.get_cost_display() == "$50,000.00"
    assert fin.display_details()["Institution"] == "Crypto Exchange"

    cloud = CloudStorageAssetInfo(storage_capacity_gb=200.0, used_storage_gb=85.0)
    assert cloud.display_details()["Storage Capacity"] == "200 GB"

    social = SocialMediaAssetInfo(platform_handle="@alex_legacy", memorialization_supported=True)
    assert social.display_details()["Memorialization"] == "Supported"

    gen = GenericAssetInfo(category_name="Domain Name", custom_properties={"Registrar": "Namecheap"})
    assert gen.display_details()["Registrar"] == "Namecheap"


def test_cancel_policy_execution():
    p_email = CancelPolicy(
        action_name="Cancel Subscription",
        execution_method="email_notice",
        support_email="support@spotify.com",
    )
    res_email = p_email.execute_action("Spotify", "https://spotify.com", "alex@gmail.com")
    assert res_email["method"] == "email_notice"
    assert "alex@gmail.com" in res_email["email_body"]

    p_portal = CancelPolicy(
        action_name="Data Transfer",
        execution_method="web_portal",
        target_url="https://google.com/portal",
    )
    res_portal = p_portal.execute_action("Google", "https://google.com", "alex@gmail.com")
    assert res_portal["method"] == "web_portal"
    assert res_portal["portal_url"] == "https://google.com/portal"

    p_probate = CancelPolicy(
        action_name="Probate Asset Recovery",
        execution_method="probate_filing",
    )
    res_probate = p_probate.execute_action("Coinbase", "https://coinbase.com", "alex@crypto.com")
    assert res_probate["method"] == "probate_filing"
    assert len(res_probate["steps"]) >= 3


def test_asset_creation_and_table_serialization():
    death_pol, cancel_pol = get_policies_for_service("Spotify", "https://spotify.com")
    asset = Asset(
        service="Spotify",
        service_address="https://spotify.com",
        username="alex.music@gmail.com",
        death_policy=death_pol,
        cancel_policy=cancel_pol,
        asset_info=SubscriptionAssetInfo(cost_monthly=10.99, plan_tier="Individual"),
        heir="Jordan",
        status="Active",
    )

    assert asset.service == "Spotify"
    assert asset.service_address == "https://spotify.com"
    assert asset.username == "alex.music@gmail.com"
    assert asset.category == "Subscription"
    assert asset.cost_monthly == 10.99

    # Table row roundtrip
    row = asset.to_table_row()
    assert row["Username"] == "alex.music@gmail.com"
    assert row["Service Address"] == "https://spotify.com"
    assert row["Type"] == "Subscription"

    rebuilt = Asset.from_table_row(row)
    assert rebuilt.service == "Spotify"
    assert rebuilt.username == "alex.music@gmail.com"
    assert rebuilt.service_address == "https://spotify.com"


def test_default_assets_and_metrics():
    assets = get_default_assets()
    assert len(assets) == 5
    metrics = calculate_metrics(assets)
    assert metrics["total_services"] == 5
    assert metrics["unique_providers"] == 4
    assert float(metrics["monthly_drain_prevented"].replace("$", "")) > 0


def test_owner_cancellation_and_type_specific_dict():
    assets = get_default_assets()
    sub = assets[0]
    
    # Test owner cancellation plan
    plan = sub.cancel_policy.get_owner_cancellation_plan(
        service=sub.service,
        service_address=sub.service_address,
        username=sub.username,
    )
    assert len(plan["steps"]) >= 3
    assert "email_draft" in plan
    assert sub.username in plan["email_draft"]

    # Test type-specific dictionary representation
    t_dict = sub.to_type_specific_dict()
    assert "Monthly Cost" in t_dict
    assert "Billing Cycle" in t_dict
    assert t_dict["Service"] == "Spotify"

    # Test marking as Cancelled
    sub.status = "Cancelled"
    assert sub.status == "Cancelled"


def test_owner_removal_and_wrongly_attributed_audit():
    assets = get_default_assets()
    initial_metrics = calculate_metrics(assets)
    initial_spend = float(initial_metrics["active_monthly_spend"].replace("$", ""))
    initial_total = initial_metrics["total_services"]

    # 1. Owner removes an account
    target = assets[0]
    sub_cost = target.cost_monthly
    target.status = "Removed"

    metrics_after_remove = calculate_metrics(assets)
    new_spend = float(metrics_after_remove["active_monthly_spend"].replace("$", ""))
    assert metrics_after_remove["removed_count"] == 1
    assert round(new_spend, 2) == round(initial_spend - sub_cost, 2)
    assert metrics_after_remove["total_services"] == initial_total - 1

    # 2. Owner restores the account
    target.status = "Active"
    metrics_after_restore = calculate_metrics(assets)
    assert metrics_after_restore["removed_count"] == 0
    assert float(metrics_after_restore["active_monthly_spend"].replace("$", "")) == initial_spend

    # 3. Heir/Executor flags an account as Wrongly Attributed (never deleted)
    fin_asset = assets[2]
    fin_asset.status = "Wrongly Attributed"
    metrics_after_wrong = calculate_metrics(assets)
    assert metrics_after_wrong["wrongly_attributed_count"] == 1
    # Remains in total estate records
    assert len(assets) == 5

    # 4. Table serialization preserves these statuses
    row_removed = target.to_table_row()
    row_removed["Status"] = "Removed"
    rebuilt_rem = Asset.from_table_row(row_removed)
    assert rebuilt_rem.status == "Removed"

    row_wrong = fin_asset.to_table_row()
    rebuilt_wrong = Asset.from_table_row(row_wrong)
    assert rebuilt_wrong.status == "Wrongly Attributed"


def test_multi_type_assets():
    death_pol, cancel_pol = get_policies_for_service("Google One", "https://one.google.com")
    multi_asset = Asset(
        service="Google One",
        service_address="https://one.google.com",
        username="alex.backup@gmail.com",
        death_policy=death_pol,
        cancel_policy=cancel_pol,
        asset_infos=[
            CloudStorageAssetInfo(
                storage_capacity_gb=200.0,
                used_storage_gb=85.0,
                contains_sensitive_data=True,
                data_types=["Photos", "Tax Returns"],
            ),
            SubscriptionAssetInfo(
                cost_monthly=2.99,
                plan_tier="200 GB Plan",
                billing_cycle="monthly",
                renewal_date="2026-10-15",
            ),
        ],
        heir="Jordan",
        status="Active",
    )

    # 1. Multi-type identification
    assert len(multi_asset.types) == 2
    assert "Cloud Storage" in multi_asset.types
    assert "Subscription" in multi_asset.types
    assert multi_asset.has_type("Cloud Storage")
    assert multi_asset.has_type("Subscription")
    assert not multi_asset.has_type("Crypto / Finance")
    assert "Cloud Storage, Subscription" in multi_asset.category

    # 2. Get info by type
    cloud_info = multi_asset.get_info("Cloud Storage")
    sub_info = multi_asset.get_info("Subscription")
    assert isinstance(cloud_info, CloudStorageAssetInfo)
    assert cloud_info.storage_capacity_gb == 200.0
    assert isinstance(sub_info, SubscriptionAssetInfo)
    assert sub_info.cost_monthly == 2.99

    # 3. Cost aggregation
    assert multi_asset.cost_monthly == 2.99
    assert multi_asset.cost_display == "$2.99/mo"

    # 4. Tailored type-specific dict representations
    sub_dict = multi_asset.to_type_specific_dict(target_type="Subscription")
    assert "Plan" in sub_dict
    assert sub_dict["Plan"] == "200 GB Plan"
    assert "Monthly Cost" in sub_dict

    cloud_dict = multi_asset.to_type_specific_dict(target_type="Cloud Storage")
    assert "Capacity" in cloud_dict
    assert cloud_dict["Capacity"] == "200 GB"
    assert cloud_dict["Used"] == "85.0 GB"

    # 5. Adding another type dynamically (e.g. Social Media presence)
    multi_asset.add_type_info(SocialMediaAssetInfo(platform_handle="@alex_google"))
    assert multi_asset.has_type("Social Media")
    assert len(multi_asset.types) == 3

    # 6. Table serialization with multiple types
    t_row = multi_asset.to_table_row()
    assert "Cloud Storage" in t_row["Type"]
    assert "Subscription" in t_row["Type"]

    rebuilt = Asset.from_table_row(t_row)
    assert rebuilt.has_type("Cloud Storage")
    assert rebuilt.has_type("Subscription")


if __name__ == "__main__":
    test_asset_info_polymorphism()
    test_cancel_policy_execution()
    test_asset_creation_and_table_serialization()
    test_default_assets_and_metrics()
    test_owner_cancellation_and_type_specific_dict()
    test_owner_removal_and_wrongly_attributed_audit()
    test_multi_type_assets()
    print("ALL TESTS PASSED SUCCESSFULLY!")


