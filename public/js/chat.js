import { addChatMessage } from "./render.js";

function normalize(value) {
    return value
        .toLowerCase()
        .normalize("NFD")
        .replace(/[\u0300-\u036f]/g, "");
}

export function initChat({ cityIndex, sendChat, fetchWeatherByCity }) {
    const chatToggle = document.getElementById("chatToggle");
    const chatBox = document.getElementById("chatBox");
    const chatInput = document.getElementById("chatInput");
    const chatSendBtn = document.getElementById("chatSendBtn");

    if (!chatToggle || !chatBox || !chatInput || !chatSendBtn) return;

    chatToggle.addEventListener("click", () => {
        chatBox.classList.toggle("hidden");
        chatToggle.classList.toggle("active");
    });

    async function resolveCityFromQuestion(question) {
        const q = normalize(question);
        const cities = await cityIndex();
        const sorted = [...cities].sort((a, b) => b.name.length - a.name.length);
        return sorted.find(city => q.includes(normalize(city.name))) || null;
    }

    async function sendMessage() {
        const question = chatInput.value.trim();
        if (!question) return;

        addChatMessage("user", question);
        chatInput.value = "";

        let city = null;
        let weatherData = null;
        try {
            city = await resolveCityFromQuestion(question);
            if (city) {
                weatherData = await fetchWeatherByCity(city);
            }
            const response = await sendChat({
                question,
                city: city?.name,
                weatherData,
            });
            addChatMessage("bot", response.text || "Nessuna risposta disponibile.");
        } catch (error) {
            addChatMessage("bot", error.message || "La chat meteo non è disponibile al momento.");
        }
    }

    chatSendBtn.addEventListener("click", sendMessage);
    chatInput.addEventListener("keypress", event => {
        if (event.key === "Enter") sendMessage();
    });
}
