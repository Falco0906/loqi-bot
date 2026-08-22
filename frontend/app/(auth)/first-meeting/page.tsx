"use client";

import FirstMeeting from "../../../components/auth/FirstMeeting";
import { usePageTitle } from "../../../hooks/usePageTitle";

export default function FirstMeetingPage() {
  usePageTitle("Welcome");
  return <FirstMeeting />;
}
