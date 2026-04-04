export function createAutocomplete({ input, list, getLocalMatches, onSelect }) {
    let currentFocus = -1;
    let timer = null;

    function closeAllLists() {
        list.classList.add("hidden");
        list.innerHTML = "";
        currentFocus = -1;
    }

    function renderItems(items) {
        if (!items.length) {
            closeAllLists();
            return;
        }
        list.classList.remove("hidden");
        list.innerHTML = "";
        items.forEach((city, index) => {
            const item = document.createElement("div");
            item.className = "autocomplete-item";
            item.dataset.index = index;
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
        closeAllLists();
        if (value.length < 2) return;

        clearTimeout(timer);
        timer = setTimeout(async () => {
            const items = await getLocalMatches(value);
            renderItems(items);
        }, 80);
    });

    input.addEventListener("keydown", event => {
        const items = list.getElementsByClassName("autocomplete-item");
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
