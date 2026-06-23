.PHONY: help manifest bindings smoke test
help: ## List targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-10s %s\n",$$1,$$2}'
manifest: ## Print the connector manifest
	urirun-connector-email manifest
bindings: ## Print urirun bindings
	urirun-connector-email bindings
smoke: ## bindings -> urirun connectors smoke (send dry-run, no server needed)
	urirun-connector-email bindings | urirun connectors smoke - \
	  --run 'email://host/message/command/send' --payload '{"to":"a@b.com","subject":"hi","body":"hello"}' \
	  --allow 'email://*' --name email
test: ## Install editable + smoke
	pip install -e . && python3 -m pytest -q && $(MAKE) smoke
