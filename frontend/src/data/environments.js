import lectureHallCard from '../assets/choose-enviroment-page/lecture-hall-card.png'
import privateTutorCard from '../assets/choose-enviroment-page/private-tutor-call-card.png'
import studyCafeCard from '../assets/choose-enviroment-page/study-friend-cafe-card.png'
import friendAskingQuestion from '../assets/avatars/friend/asking_question.png'
import friendIdle from '../assets/avatars/friend/idle.png'
import friendListening from '../assets/avatars/friend/listening.png'
import friendSpeaking from '../assets/avatars/friend/speaking.png'
import friendThinking from '../assets/avatars/friend/thinking.png'
import professorAskingQuestion from '../assets/avatars/professor/asking_question.png'
import professorIdle from '../assets/avatars/professor/idle.png'
import professorListening from '../assets/avatars/professor/listening.png'
import professorSpeaking from '../assets/avatars/professor/speaking.png'
import professorThinking from '../assets/avatars/professor/thinking.png'
import tutorAskingQuestion from '../assets/avatars/tutor/asking_question.png'
import tutorIdle from '../assets/avatars/tutor/idle.png'
import tutorListening from '../assets/avatars/tutor/listening.png'
import tutorSpeaking from '../assets/avatars/tutor/speaking.png'
import tutorThinking from '../assets/avatars/tutor/thinking.png'
import lectureHallBackground from '../assets/environments/lecture-hall/background.png'
import privateTutorBackground from '../assets/environments/private-tutor/background.png'
import studyFriendBackground from '../assets/environments/study-friend/background.png'

const professorAvatars = {
  asking_question: professorAskingQuestion,
  idle: professorIdle,
  listening: professorListening,
  speaking: professorSpeaking,
  thinking: professorThinking,
}

const tutorAvatars = {
  asking_question: tutorAskingQuestion,
  idle: tutorIdle,
  listening: tutorListening,
  speaking: tutorSpeaking,
  thinking: tutorThinking,
}

const friendAvatars = {
  asking_question: friendAskingQuestion,
  idle: friendIdle,
  listening: friendListening,
  speaking: friendSpeaking,
  thinking: friendThinking,
}

export const environments = [
  {
    id: 'lecture-hall',
    name: 'Lecture Hall',
    image: lectureHallCard,
    background: lectureHallBackground,
    features: [
      'Formal professor delivery',
      'Deeper academic questions',
      'Structured lecture pacing',
    ],
    avatar: professorIdle,
    avatars: professorAvatars,
  },
  {
    id: 'private-tutor',
    name: 'Private Tutor Call',
    image: privateTutorCard,
    background: privateTutorBackground,
    features: [
      'Personal step-by-step coaching',
      'Lecture summary for revision',
      'Frequent understanding checks',
    ],
    avatar: tutorIdle,
    avatars: tutorAvatars,
  },
  {
    id: 'study-cafe',
    name: 'Study Friend Cafe',
    image: studyCafeCard,
    background: studyFriendBackground,
    features: [
      'Casual study-partner voice',
      'Everyday analogies',
      'Light, playful explanations',
    ],
    avatar: friendIdle,
    avatars: friendAvatars,
  },
]
