const SUN = "#f59e0b";
const MOON = "#e2e8f0";
const CLOUD = "#64748b";
const CLOUD_DARK = "#475569";
const RAIN = "#1d4ed8";

export const SVG_ICONS = {
    "02d": `<svg class="weather-icon-svg" viewBox="0 0 64 64" aria-hidden="true" xmlns="http://www.w3.org/2000/svg">
        <circle cx="17" cy="17" r="8" fill="${SUN}"/>
        <g stroke="${SUN}" stroke-width="2" stroke-linecap="round">
            <line x1="17" y1="4"  x2="17" y2="7"/>
            <line x1="17" y1="27" x2="17" y2="30"/>
            <line x1="4"  y1="17" x2="7"  y2="17"/>
            <line x1="27" y1="17" x2="30" y2="17"/>
            <line x1="9"  y1="9"  x2="11" y2="11"/>
            <line x1="23" y1="23" x2="25" y2="25"/>
            <line x1="9"  y1="25" x2="11" y2="23"/>
            <line x1="23" y1="9"  x2="25" y2="11"/>
        </g>
        <circle cx="26" cy="46" r="10" fill="${CLOUD}"/>
        <circle cx="37" cy="40" r="12" fill="${CLOUD}"/>
        <circle cx="49" cy="44" r="9"  fill="${CLOUD}"/>
        <rect x="16" y="46" width="42" height="12" fill="${CLOUD}"/>
    </svg>`,

    "02n": `<svg class="weather-icon-svg" viewBox="0 0 64 64" aria-hidden="true" xmlns="http://www.w3.org/2000/svg">
        <path fill-rule="evenodd" fill="${MOON}" d="M16,5 A13,13 0 0 1 16,31 A13,13 0 0 1 16,5 Z M22,3 A11,11 0 0 1 22,25 A11,11 0 0 1 22,3 Z"/>
        <circle cx="26" cy="46" r="10" fill="${CLOUD}"/>
        <circle cx="37" cy="40" r="12" fill="${CLOUD}"/>
        <circle cx="49" cy="44" r="9"  fill="${CLOUD}"/>
        <rect x="16" y="46" width="42" height="12" fill="${CLOUD}"/>
    </svg>`,

    "10d": `<svg class="weather-icon-svg" viewBox="0 0 64 64" aria-hidden="true" xmlns="http://www.w3.org/2000/svg">
        <circle cx="11" cy="11" r="6" fill="${SUN}"/>
        <g stroke="${SUN}" stroke-width="1.5" stroke-linecap="round">
            <line x1="11" y1="2"  x2="11" y2="4"/>
            <line x1="11" y1="18" x2="11" y2="20"/>
            <line x1="2"  y1="11" x2="4"  y2="11"/>
            <line x1="18" y1="11" x2="20" y2="11"/>
            <line x1="5"  y1="5"  x2="7"  y2="7"/>
            <line x1="15" y1="5"  x2="17" y2="7"/>
        </g>
        <circle cx="22" cy="40" r="9"  fill="${CLOUD}"/>
        <circle cx="33" cy="35" r="11" fill="${CLOUD}"/>
        <circle cx="46" cy="39" r="9"  fill="${CLOUD}"/>
        <rect x="13" y="40" width="42" height="10" fill="${CLOUD}"/>
        <g stroke="${RAIN}" stroke-width="2.5" stroke-linecap="round">
            <line x1="22" y1="54" x2="19" y2="62"/>
            <line x1="33" y1="54" x2="30" y2="62"/>
            <line x1="44" y1="54" x2="41" y2="62"/>
        </g>
    </svg>`,

    "10n": `<svg class="weather-icon-svg" viewBox="0 0 64 64" aria-hidden="true" xmlns="http://www.w3.org/2000/svg">
        <path fill-rule="evenodd" fill="${MOON}" d="M11,4 A9,9 0 0 1 11,22 A9,9 0 0 1 11,4 Z M16,3 A7,7 0 0 1 16,17 A7,7 0 0 1 16,3 Z"/>
        <circle cx="22" cy="40" r="9"  fill="${CLOUD}"/>
        <circle cx="33" cy="35" r="11" fill="${CLOUD}"/>
        <circle cx="46" cy="39" r="9"  fill="${CLOUD}"/>
        <rect x="13" y="40" width="42" height="10" fill="${CLOUD}"/>
        <g stroke="${RAIN}" stroke-width="2.5" stroke-linecap="round">
            <line x1="22" y1="54" x2="19" y2="62"/>
            <line x1="33" y1="54" x2="30" y2="62"/>
            <line x1="44" y1="54" x2="41" y2="62"/>
        </g>
    </svg>`,

    "09d": `<svg class="weather-icon-svg" viewBox="0 0 64 64" aria-hidden="true" xmlns="http://www.w3.org/2000/svg">
        <circle cx="16" cy="38" r="10" fill="${CLOUD_DARK}"/>
        <circle cx="28" cy="32" r="13" fill="${CLOUD_DARK}"/>
        <circle cx="44" cy="34" r="12" fill="${CLOUD_DARK}"/>
        <circle cx="54" cy="38" r="9"  fill="${CLOUD_DARK}"/>
        <rect x="6" y="38" width="57" height="12" fill="${CLOUD_DARK}"/>
        <g stroke="${RAIN}" stroke-width="2.5" stroke-linecap="round">
            <line x1="14" y1="54" x2="11" y2="63"/>
            <line x1="23" y1="54" x2="20" y2="63"/>
            <line x1="32" y1="54" x2="29" y2="63"/>
            <line x1="41" y1="54" x2="38" y2="63"/>
            <line x1="50" y1="54" x2="47" y2="63"/>
        </g>
    </svg>`,

    "09n": `<svg class="weather-icon-svg" viewBox="0 0 64 64" aria-hidden="true" xmlns="http://www.w3.org/2000/svg">
        <circle cx="16" cy="38" r="10" fill="${CLOUD_DARK}"/>
        <circle cx="28" cy="32" r="13" fill="${CLOUD_DARK}"/>
        <circle cx="44" cy="34" r="12" fill="${CLOUD_DARK}"/>
        <circle cx="54" cy="38" r="9"  fill="${CLOUD_DARK}"/>
        <rect x="6" y="38" width="57" height="12" fill="${CLOUD_DARK}"/>
        <g stroke="${RAIN}" stroke-width="2.5" stroke-linecap="round">
            <line x1="14" y1="54" x2="11" y2="63"/>
            <line x1="23" y1="54" x2="20" y2="63"/>
            <line x1="32" y1="54" x2="29" y2="63"/>
            <line x1="41" y1="54" x2="38" y2="63"/>
            <line x1="50" y1="54" x2="47" y2="63"/>
        </g>
    </svg>`,
};
