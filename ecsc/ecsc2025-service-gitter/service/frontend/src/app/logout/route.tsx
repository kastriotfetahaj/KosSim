import { NextRequest } from "next/server";
import { redirect } from "next/navigation";
import { logout } from "@/lib/auth";

export async function POST(request: NextRequest) {
  await logout();
  redirect("/");
}
