frappe.listview_settings["Notification Engine Log"] = {
	add_fields: ["status", "channel"],
	get_indicator: function (doc) {
		if (doc.status === "Success") {
			return [__("Success"), "green", "status,=,Success"];
		}
		if (doc.status === "Failed") {
			return [__("Failed"), "red", "status,=,Failed"];
		}
		if (doc.status === "Skipped") {
			return [__("Skipped"), "orange", "status,=,Skipped"];
		}
		if (doc.status === "Queued") {
			return [__("Queued"), "blue", "status,=,Queued"];
		}
	},
};
