// Copyright (c) 2026, Galaxy Labs and contributors
// For license information, please see license.txt

// frappe.ui.form.on("Route", {
// 	refresh(frm) {

// 	},
// });
frappe.ui.form.on('Route', {
  refresh(frm) {
    // ✅ Load Places (autocomplete only, no fetching)
    if (!window.google || !window.google.maps || !window.google.maps.places) {
      load_google_places(frm);
    } else {
      init_route_autocomplete(frm);
    }

    // ✅ Button only after save
    if (!frm.is_new()) {
      frm.add_custom_button(__('Fetch Distance'), () => fetch_after_save(frm), __('Actions'));
    }
  }
});

// -------------------- BUTTON: after save fetch --------------------
function fetch_after_save(frm) {
  frappe.call({
    method: "tms.transport_management_system.doctype.route.route.fetch_distance_for_route",
    args: { route_name: frm.doc.name },
    freeze: true,
    freeze_message: __("Fetching distance..."),
    callback(r) {
      if (!r.message) return;

      // values are db_set in server, reload
      frm.reload_doc();

      frappe.show_alert({ message: __("Distance updated"), indicator: "green" });
    }
  });
}

// -------------------- GOOGLE PLACES LOADER --------------------
function load_google_places(frm) {
  const GOOGLE_KEY = "AIzaSyCjiluJNwjXl7V2d7MIFomsa_Nhl4b0sqM";
  const url = `https://maps.googleapis.com/maps/api/js?key=${GOOGLE_KEY}&libraries=places`;

  if (window.__google_places_loading) return;
  window.__google_places_loading = true;

  $.getScript(url)
    .done(() => init_route_autocomplete(frm))
    .fail(() => frappe.msgprint("Google Places API failed to load. Check key / restrictions."));
}

// -------------------- AUTOCOMPLETE (KSA ONLY) --------------------
function init_route_autocomplete(frm) {
  const options = {
    componentRestrictions: { country: ["sa"] }, // ✅ KSA only
    fields: ["name", "formatted_address"]       // ✅ we need formatted_address
  };

  // FROM
  const from_input = frm.fields_dict.from_city?.input;
  if (from_input && !from_input.__places_bound) {
    const ac1 = new google.maps.places.Autocomplete(from_input, options);
    ac1.addListener("place_changed", function () {
      const place = ac1.getPlace();

      // ✅ clean short name only (no duplication ever)
      const short_name = (place?.name || "").trim();
      frm.set_value("from_city", short_name);

      // ✅ full address goes to from_place_full (if available)
      const full = (place?.formatted_address || short_name).trim();
      frm.set_value("from_place_full", full);
    });
    from_input.__places_bound = true;
  }

  // TO
  const to_input = frm.fields_dict.to_city?.input;
  if (to_input && !to_input.__places_bound) {
    const ac2 = new google.maps.places.Autocomplete(to_input, options);
    ac2.addListener("place_changed", function () {
      const place = ac2.getPlace();

      // ✅ clean short name only
      const short_name = (place?.name || "").trim();
      frm.set_value("to_city", short_name);

      // ✅ full address goes to to_place_full
      const full = (place?.formatted_address || short_name).trim();
      frm.set_value("to_place_full", full);
    });
    to_input.__places_bound = true;
  }
}
