 // XQL query produced by Spellbook by GoCortex (https://spellbook.gocortex.io/)
// Issues, questions or feature requests can be raised here; https://github.com/gocortexio/spellbook
//
// First 'config timeframe' sets the datasource look-back period (your retro-hunt period)
 config timeframe = %%LOOKBACK%%
| dataset = %%DATASET%%
//
// These fields are specific to PANW Traffic logs, you will need to select the fields that you feel are important to capture and filter on to ensure your search matches the use case, this could include fields from Auth sources (i.e. MFA status)
| fields session_end_reason, rule_matched, _reporting_device_name, users, source_ip, dest_port, action, _time, rule_matched, dest_port, dest_ip
//
| alter source_ipv4 =  source_ip
| alter target_ipv4 = dest_ip
| alter target_port = dest_port
| alter source_user_username = users
//
// Ensure you "cleanup" the data before presenting the fields to functions such as is_known_private_ipv4 especially for long-term look-backs (CRTX-231221)
| filter source_ipv4 ~= "^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}" or source_ipv4  ~= "(?i)[0-9a-f]*:"
| filter target_ipv4 ~= "^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}" or target_ipv4  ~= "(?i)[0-9a-f]*:"
//
// Consider efficiencies of searches for a threat-intel IP based match on a destination, its unlikely to ever be an RFC1918 IP address, so exclude those.
// Consider the topology of your network for source matches, some technologies log rejected flows "reflecting" of the public edge, so decide how you want to filter the source, also consider similar logic for non network flow based rules
| filter (is_known_private_ipv4(source_ipv4) and not is_known_private_ipv4(target_ipv4)) or (is_known_private_ipv6(source_ipv4) and not is_known_private_ipv6(target_ipv4))
//
// The 'type = inner' specifies an inner join, which returns only records that have matching values in both datasets.
// The 'conflict_strategy = left' is used to resolve field name conflicts when joining datasets with overlapping field names
| join conflict_strategy = left type = inner
//
// Second config sets the indicator (your threat intel source) look-back, if you are doing runs daily then you only need to use the last-24h changed intel data.
( config timeframe = 24h 
    | dataset = indicators
    //
    // Filter in the values you want to compare again these values are most common for most use cases
    | filter type = "IP" and verdict = "Malicious" and expiration_status = "active"
    //
    // Where possible use a value from the XDM adacent field names at the top for the MATCH_FIELD
    | fields value, type , verdict , expiration_status , tags) as tim_threat_intel tim_threat_intel.value = %%MATCH_FIELD%%
//
// Ensure you 'alter' the _time otherwise your newly stamped matched results will inherit the dataset _time and as such be backdated, we preserve that value in the 'matched_dataset' field. 'matched_timeframe' acts as an important historical record in our output dataset.
| alter event_time = _time
| alter _time = current_time()
| alter matched_dataset = " %%DATASET%%"
| alter matched_timeframe = "%%LOOKBACK%%"
| alter matched_field = "%%MATCH_FIELD%%"
//
// Try and bring down your fields from the top of this search and merge these with the newly joined 'indicators' data
| comp count() by event_time, session_end_reason, rule_matched, _reporting_device_name, source_user_username, source_ipv4, target_port, action, target_ipv4, matched_dataset, matched_timeframe, matched_field, verdict
| limit 10000000
| target type = dataset append = true intelmatch_gc_raw