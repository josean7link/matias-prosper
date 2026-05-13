import { redirect } from "next/navigation";
export default function OperationsRoot() {
  redirect("/admin/operations/transactions");
}
