import { MDXRemote } from "next-mdx-remote/rsc";
import Link from "next/link";

const components = {
  a: ({ href = "", children }: { href?: string; children?: React.ReactNode }) =>
    href.startsWith("/") ? (
      <Link href={href}>{children}</Link>
    ) : (
      <a href={href} rel="noopener noreferrer">
        {children}
      </a>
    ),
};

export function Mdx({ source }: { source: string }) {
  return (
    <div className="prose-article">
      <MDXRemote source={source} components={components} />
    </div>
  );
}
