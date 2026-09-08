/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./index.html", "./src/**/*.{js,jsx,ts,tsx}"],
  theme: {
    extend: {
      colors: {
        paper: {
          DEFAULT: "#F5F0E6",
          deep: "#EDE6D8",
        },
        ink: {
          DEFAULT: "#1C1917",
          soft: "#5F594F",
        },
        accent: "#2F5573",
        verified: "#0E9384",
        rejected: "#B3402A",
        gold: "#B08D57",
      },
    },
  },
  plugins: [],
}
