import type { Metadata } from 'next';
import './globals.css';
export const metadata: Metadata = { title:'רישוי פתוח | בדיקת רכב לפי מספר רישוי',description:'בדיקת פרטי רכב ממקורות מידע עם תיעוד מקור וכיסוי.' };
export default function RootLayout({children}:{children:React.ReactNode}) {return <html lang="he" dir="rtl"><body>{children}</body></html>}
