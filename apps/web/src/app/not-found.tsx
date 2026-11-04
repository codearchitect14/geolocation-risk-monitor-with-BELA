import Link from "next/link";
import { Button } from "@/components/ui/button";

export default function NotFound() {
  return (
    <section className="container-page section-pad text-center">
      <p className="text-small font-semibold uppercase tracking-wider text-teal-700">Not found</p>
      <h1 className="mt-3 text-h1">This page does not exist</h1>
      <p className="mx-auto mt-4 max-w-md text-slate-700">
        The address may be mistyped or the page may have moved.
      </p>
      <Button asChild className="mt-8">
        <Link href="/">Go to the home page</Link>
      </Button>
    </section>
  );
}
