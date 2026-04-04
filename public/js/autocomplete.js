export function createAutocomplete({ input, list, getSuggestions, onSelect }) {
    let currentFocus = -1;
    let timer = null;
    let currentController = null;
    let latestRequestId = 0;

    function abortPendingRequest() {
        if (!currentController) return;
        currentController.abort();
        currentController = null;
    }

    function closeAllLists() {
        list.classList.add("hidden");
        list.innerHTML = "";
        currentFocus = -1;
    }

    function renderStatus(message, { loading = false } = {}) {
        list.classList.remove("hidden");
        list.innerHTML = "";

        const item = document.createElement("div");
        item.className = `autocomplete-status${loading ? " is-loading" : ""}`;
        item.innerHTML = `
            <i class="fas ${loading ? "fa-spinner fa-spin" : "fa-circle-info"}"></i>
            <span>${message}</span>
        `;
        list.appendChild(item);
    }

    function renderItems(items) {
        if (!items.length) {
            renderStatus("Nessuna città trovata");
            return;
        }
        list.classList.remove("hidden");
        list.innerHTML = "";
        items.forEach((city, index) => {
            const item = document.createElement("div");
            item.className = "autocomplete-item";
            item.dataset.index = index;
            item.dataset.selectable = "true";
            item.innerHTML = `
                <i class="fas fa-map-marker-alt"></i>
                <span class="city-name">${city.name}</span>
                ${city.region ? `<span class="region">${city.region}</span>` : ""}
            `;
            item.addEventListener("click", () => {
                input.value = city.name;
                closeAllLists();
                onSelect(city);
            });
            list.appendChild(item);
        });
    }

    function setActive(items) {
        [...items].forEach(item => item.classList.remove("active"));
        if (!items.length) return;
        if (currentFocus >= items.length) currentFocus = 0;
        if (currentFocus < 0) currentFocus = items.length - 1;
        items[currentFocus].classList.add("active");
    }

    input.addEventListener("input", () => {
        const value = input.value.trim();
        clearTimeout(timer);
        abortPendingRequest();
        currentFocus = -1;

        if (!value.length) {
            closeAllLists();
            return;
        }
        if (value.length < 2) {
            closeAllLists();
            return;
        }

        timer = setTimeout(async () => {
            const requestValue = input.value.trim();
            if (requestValue.length < 2) {
                closeAllLists();
                return;
            }

            const requestId = ++latestRequestId;
            const controller = new AbortController();
            currentController = controller;
            renderStatus("Cerco città...", { loading: true });

            try {
                const items = await getSuggestions(requestValue, { signal: controller.signal });
                if (requestId !== latestRequestId || input.value.trim() !== requestValue) return;
                renderItems(items);
            } catch (error) {
                if (error?.name === "AbortError") return;
                if (requestId !== latestRequestId || input.value.trim() !== requestValue) return;
                renderStatus("Suggerimenti non disponibili");
            } finally {
                if (currentController === controller) {
                    currentController = null;
                }
            }
        }, 120);
    });

    input.addEventListener("keydown", event => {
        const items = list.querySelectorAll('.autocomplete-item[data-selectable="true"]');
        if (event.key === "ArrowDown") {
            currentFocus++;
            setActive(items);
            event.preventDefault();
        } else if (event.key === "ArrowUp") {
            currentFocus--;
            setActive(items);
            event.preventDefault();
        } else if (event.key === "Enter") {
            if (currentFocus > -1 && items[currentFocus]) {
                event.preventDefault();
                items[currentFocus].click();
            }
        } else if (event.key === "Escape") {
            closeAllLists();
        }
    });

    document.addEventListener("click", event => {
        if (event.target !== input && event.target !== list) {
            closeAllLists();
        }
    });
}
