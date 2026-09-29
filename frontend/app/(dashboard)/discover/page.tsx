import { redirect } from "next/navigation";

/** Legacy URL retained for bookmarks; /discovery is the primary surface. */
export default function DiscoverRedirect() {
  redirect("/discovery");
}
