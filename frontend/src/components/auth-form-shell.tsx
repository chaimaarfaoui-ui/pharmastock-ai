import { Pill } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export function AuthShell({ title, subtitle, children }: { title: string; subtitle: string; children: React.ReactNode }) {
  return (
    <main className="flex min-h-screen items-center justify-center bg-muted p-4">
      <div className="w-full max-w-md space-y-6">
        <div className="flex items-center justify-center gap-2 text-lg font-semibold">
          <Pill className="h-6 w-6 text-primary" aria-hidden /> PharmaStock AI
        </div>
        <Card>
          <CardHeader><CardTitle className="text-xl">{title}</CardTitle><p className="text-sm text-muted-foreground">{subtitle}</p></CardHeader>
          <CardContent>{children}</CardContent>
        </Card>
      </div>
    </main>
  );
}
