"use client";

import { motion, useReducedMotion } from "framer-motion";
import * as React from "react";

/** Subtle reveal on scroll. Only position animates, so content stays visible without script and when the user prefers reduced motion. */
export function Reveal({
  children,
  delay = 0,
  className,
}: {
  children: React.ReactNode;
  delay?: number;
  className?: string;
}) {
  const reduce = useReducedMotion();
  if (reduce) return <div className={className}>{children}</div>;
  return (
    <motion.div
      className={className}
      initial={{ y: 12 }}
      whileInView={{ y: 0 }}
      viewport={{ once: true, margin: "0px 0px -60px 0px" }}
      transition={{ duration: 0.25, ease: "easeOut", delay }}
    >
      {children}
    </motion.div>
  );
}
