// XQL query produced by Spellbook by GoCortex (https://spellbook.gocortex.io/)
// Issues, questions or feature requests can be raised here; https://github.com/gocortexio/spellbook
//
// ============================================================================
// UNIVERSAL THREAT INTEL HUNT TEMPLATE
// ============================================================================
//
// This template matches events from any data source against the Cortex XSIAM
// threat intelligence (indicators) dataset. It supports six hunt types:
//
//   Hunt Type       | %%INDICATOR_TYPE%%    | %%MATCH_FIELD%%           | Typical Sources
//   ----------------|-----------------------|---------------------------|---------------------------
//   IP address      | "IP"                  | source_ipv4 or target_ipv4| Firewall, proxy, NDR
//   Domain          | "Domain"              | target_domain             | DNS, proxy, web filter
//   File hash SHA256| "FileHash-SHA256"     | file_hash_sha256          | EDR, sandbox, email GW
//   File hash MD5   | "FileHash-MD5"        | file_hash_md5             | EDR, sandbox, email GW
//   Username        | "Username"            | source_user_username or   | Okta, Azure AD, Duo,
//                   |                       | target_user_username      | Active Directory
//   URL             | "URL"                 | target_url                | Proxy, web filter, CASB
//   Software        | "SOFTWARE"            | software_package_purl     | SBOM, SCA, SAST
//
// ============================================================================
// HOW TO ADAPT THIS TEMPLATE
// ============================================================================
//
// Step 1: Set the four placeholders
//   %%LOOKBACK%%         Retro-hunt period (e.g. 30d, 7d, 24h)
//   %%DATASET%%          Source dataset (e.g. panw_ngfw_traffic_raw)
//   %%INDICATOR_TYPE%%   Indicator type from the table above
//   %%MATCH_FIELD%%      Intermediary field name to join on (from the table above)
//
// Step 2: Update %%SOURCE_FIELDS%% with the raw field names from your data source
//   These are the product-specific column names you want to pull through.
//   Only list the fields your source actually provides.
//
// Step 3: Update the FIELD MAPPING section (Section B)
//   Map each raw source field to the correct intermediary name.
//   Set any field your source does not provide to null (it is already null by default).
//   Only uncomment the filter sections relevant to your hunt type.
//
// ============================================================================
// SOURCE FIELD EXAMPLES (for %%SOURCE_FIELDS%%)
// ============================================================================
//
// PANW Traffic:
// Fields extracted natively via Parser
//   session_end_reason, rule_matched, _reporting_device_name, users, source_ip, source_port, dest_ip, dest_port, action, app, protocol, _time
//
// Okta System Logs:
// May require JSON based extraction
//   | alter actor_displayName = json_extract_scalar(actor , "$.displayName"), actor_alternateId =  json_extract_scalar(actor , "$.alternateId"), client_ipAddress = json_extract_scalar(client, "$.ipAddress"), client_userAgent = json_extract_scalar(client, "$.userAgent"), outcome_result = json_extract_scalar(outcome, "$.result"), outcome_reason = json_extract_scalar(outcome, "$.reason"), okta_eventtype = eventType
//
// Generic Proxy / Web Filter:
//   src_ip, dst_ip, dst_port, url, domain, user, action, http_method, _time
//
// Software / SBOM (SCA, SAST):
//   package_version, package_purl, repository_name, asset_type_name, asset_provider, asset_name
//
// ============================================================================
// OUTPUT SCHEMA / XDM MAPPING REFERENCE
// ============================================================================
//
// Every output column from the comp stage maps to a known XDM field path.
// This table is the specification for the future intelmatch_gc_raw data model rule.
//
//   Output Column                | XDM Target Field              | Notes
//   -----------------------------|-------------------------------|-----------------------------
//   _time                        | xdm.event.timestamp           | Stamped with current_time() at match
//   event_time                   | (metadata)                    | Preserved original event _time
//   source_ipv4                  | xdm.source.ipv4               | Source IP address
//   source_ipv6                  | xdm.source.ipv6               | Source IPv6 address
//   source_port                  | xdm.source.port               | Source port
//   target_ipv4                  | xdm.target.ipv4               | Destination IP address
//   target_ipv6                  | xdm.target.ipv6               | Destination IPv6 address
//   target_port                  | xdm.target.port               | Destination port
//   network_application_protocol | xdm.network.application_protocol | Application-layer protocol (HTTP, DNS, SSL)
//   action_protocol              | xdm.network.ip_protocol       | Network-layer protocol (TCP, UDP, ICMP)
//   target_domain                | xdm.target.domain             | Queried / accessed domain
//   target_url                   | xdm.target.url                | Full URL accessed
//   source_user_username         | xdm.source.user.username      | Initiating user
//   source_user_domain           | xdm.source.user.domain        | Initiating user domain
//   target_user_username         | xdm.target.user.username      | Target user (priv esc, etc.)
//   target_user_domain           | xdm.target.user.domain        | Target user domain
//   auth_method                  | xdm.auth.auth_method          | Authentication method (MFA, etc.)
//   auth_outcome                 | xdm.event.outcome             | Auth result (success/failure)
//   event_type                   | xdm.event.type                | Event type (e.g. Okta eventType)
//   file_hash_sha256             | xdm.target.file.sha256        | File SHA-256 hash
//   file_hash_md5                | xdm.target.file.md5           | File MD5 hash
//   software_package_version     | (metadata)                    | Software package version
//   software_package_purl        | (metadata)                    | Package URL (purl) identifier
//   software_repository_name     | (metadata)                    | Source repository name
//   software_asset_type_name     | (metadata)                    | Asset type classification
//   software_asset_provider      | (metadata)                    | Asset provider / vendor
//   software_asset_name          | (metadata)                    | Software asset name
//   observer_name                | xdm.observer.name             | Reporting device / sensor
//   observer_action              | xdm.observer.action           | Action taken by the device
//   network_rule                 | xdm.network.rule              | Rule / policy that matched
//   network_session_reason       | xdm.event.outcome_reason      | Session end / outcome reason
//   matched_dataset              | (metadata)                    | Source dataset name
//   matched_timeframe            | (metadata)                    | Look-back period used
//   matched_field                | (metadata)                    | Which field was matched
//   indicator_type               | (from indicators)             | Indicator type (IP, Domain, etc.)
//   indicator_verdict            | (from indicators)             | Indicator verdict (Malicious, etc.)
//   indicator_tags               | (from indicators)             | Requires adding tags to join fields
//   count                        | (aggregation)                 | Number of matching events
//
// ============================================================================
// SECTION A: DATA SOURCE AND FIELD SELECTION
// ============================================================================
//
// First 'config timeframe' sets the data source look-back period (your retro-hunt period)
config timeframe = %%LOOKBACK%%
| dataset = %%DATASET%%
//
// Select the raw fields from your data source (see SOURCE FIELD EXAMPLES above)
| fields %%SOURCE_FIELDS%%
//
// ============================================================================
// SECTION B: FIELD MAPPING (edit these to match your data source)
// ============================================================================
// Map raw source field names to standardised intermediary names.
// Set any field your source does not provide to null (already null by default).
// These intermediary names align with XDM field paths for the output dataset.
//
// --- Network fields (firewalls, proxies, NDR) ---
| alter source_ipv4 = null
| alter source_ipv6 = null
| alter source_port = null
| alter target_ipv4 = null
| alter target_ipv6 = null
| alter target_port = null
| alter network_application_protocol = null
| alter action_protocol = null
//
// --- Identity / Auth fields (Okta, Azure AD, Duo, Active Directory) ---
| alter source_user_username = null
| alter source_user_domain = null
| alter target_user_username = null
| alter target_user_domain = null
| alter auth_method = null
| alter auth_outcome = null
| alter event_type = null
//
// --- Domain / URL fields (proxy, DNS, web filter, CASB) ---
| alter target_domain = null
| alter target_url = null
//
// --- File hash fields (EDR, sandbox, email gateway) ---
| alter file_hash_sha256 = null
| alter file_hash_md5 = null
//
// --- Software asset fields (SBOM, SCA, SAST) ---
| alter software_package_version = null
| alter software_package_purl = null
| alter software_repository_name = null
| alter software_asset_type_name = null
| alter software_asset_provider = null
| alter software_asset_name = null
//
// --- Observer / Device fields ---
| alter observer_name = null
| alter observer_action = null
| alter network_rule = null
| alter network_session_reason = null
//
// ============================================================================
// SECTION C: DATA QUALITY FILTERS (uncomment the sections you need)
// ============================================================================
//
// --- IP address validation (use for IP-based hunts) ---
// Ensure you "clean up" the data before presenting the fields to functions such as
// is_known_private_ipv4, especially for long-term look-backs (CRTX-231221)
//
// | filter source_ipv4 ~= "^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}" or source_ipv6 ~= "(?i)[0-9a-f]*:"
// | filter target_ipv4 ~= "^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}" or target_ipv6 ~= "(?i)[0-9a-f]*:"
//
// Consider efficiencies of searches for a threat-intel IP based match on a destination;
// it is unlikely to ever be an RFC1918 IP address, so exclude those.
// Consider the topology of your network for source matches; some technologies log
// rejected flows "reflecting" off the public edge, so decide how you want to filter
// the source. Consider similar logic for non-network-flow-based rules.
//
// | filter (is_known_private_ipv4(source_ipv4) and not is_known_private_ipv4(target_ipv4)) or (is_known_private_ipv6(source_ipv6) and not is_known_private_ipv6(target_ipv6))
//
// --- Domain validation (use for domain-based hunts) ---
// Strip trailing dots from FQDN notation and exclude internal domains
//
// | filter target_domain != null and target_domain != ""
// | alter target_domain = if(target_domain ~= "\.$", rtrim(target_domain, "."), target_domain)
//
// --- Username validation (use for username-based hunts) ---
// Exclude service accounts or empty usernames
//
// | filter source_user_username != null and source_user_username != ""
// | filter source_user_username not in ("SYSTEM", "LOCAL SERVICE", "NETWORK SERVICE")
//
// --- File hash validation (use for hash-based hunts) ---
// Ensure hashes are well-formed
//
// | filter file_hash_sha256 ~= "^[A-Fa-f0-9]{64}$" or file_hash_md5 ~= "^[A-Fa-f0-9]{32}$"
//
// ============================================================================
// SECTION D: THREAT INTELLIGENCE JOIN
// ============================================================================
//
// The 'type = inner' specifies an inner join, returning only records with matching
// values in both datasets. The 'conflict_strategy = left' resolves field name
// conflicts when joining datasets with overlapping field names.
| join conflict_strategy = left type = inner
//
// Second config sets the indicator (your threat intel source) look-back.
// If you are doing runs daily, you only need to use the last 24h changed intel data.
(config timeframe = 24h
    | dataset = indicators
    //
    // Filter the indicator type and verdict for your hunt.
    // Common types: "IP", "Domain", "FileHash-SHA256", "FileHash-MD5", "Username", "URL", "SOFTWARE"
    | filter type = "%%INDICATOR_TYPE%%" and verdict = "Malicious" and expiration_status = "active"
    //
    | fields value, type, verdict, expiration_status) as tim_threat_intel tim_threat_intel.value = %%MATCH_FIELD%%
//
// ============================================================================
// SECTION E: TIMESTAMP AND METADATA
// ============================================================================
//
// Preserve the original event time then stamp with current time. Without this
// the matched results inherit the dataset _time and appear backdated.
| alter event_time = _time
| alter _time = current_time()
| alter matched_dataset = "%%DATASET%%"
| alter matched_timeframe = "%%LOOKBACK%%"
| alter matched_field = "%%MATCH_FIELD%%"
| alter indicator_type = type
| alter indicator_verdict = verdict
//
// ============================================================================
// SECTION F: AGGREGATION AND OUTPUT
// ============================================================================
//
// Aggregate matched events. All field names are standardised intermediary names
// that map directly to XDM paths (see OUTPUT SCHEMA table above).
| comp count() by _time, event_time, source_ipv4, source_ipv6, source_port, target_ipv4, target_ipv6, target_port, network_application_protocol, action_protocol, target_domain, target_url, source_user_username, source_user_domain, target_user_username, target_user_domain, file_hash_sha256, file_hash_md5, software_package_version, software_package_purl, software_repository_name, software_asset_type_name, software_asset_provider, software_asset_name, observer_name, observer_action, network_rule, network_session_reason, auth_method, auth_outcome, event_type, matched_dataset, matched_timeframe, matched_field, indicator_type, indicator_verdict
| limit 10000000
| target type = dataset append = true intelmatch_gc_raw
