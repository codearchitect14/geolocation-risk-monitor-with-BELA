"use client";

import { createContext, useContext } from "react";

export type Theme = "light" | "dark";
export const ThemeContext = createContext<{ theme: Theme; toggle: () => void }>({
  theme: "light",
  toggle: () => undefined,
});
export const useTheme = () => useContext(ThemeContext);
