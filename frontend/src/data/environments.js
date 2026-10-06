import lectureHallCard from '../assets/choose-enviroment-page/lecture-hall-card.png'
import privateTutorCard from '../assets/choose-enviroment-page/private-tutor-call-card.png'
import studyCafeCard from '../assets/choose-enviroment-page/study-friend-cafe-card.png'
import lectureHallAvatar from '../assets/environments/lecture-hall/avatar.png'
import lectureHallBackground from '../assets/environments/lecture-hall/background.png'
import privateTutorAvatar from '../assets/environments/private-tutor/avatar.png'
import privateTutorBackground from '../assets/environments/private-tutor/background.png'
import studyFriendAvatar from '../assets/environments/study-friend/avatar.png'
import studyFriendBackground from '../assets/environments/study-friend/background.png'

export const environments = [
  {
    id: 'lecture-hall',
    name: 'Lecture Hall',
    image: lectureHallCard,
    background: lectureHallBackground,
    avatar: lectureHallAvatar,
  },
  {
    id: 'private-tutor',
    name: 'Private Tutor Call',
    image: privateTutorCard,
    background: privateTutorBackground,
    avatar: privateTutorAvatar,
  },
  {
    id: 'study-cafe',
    name: 'Study Friend Cafe',
    image: studyCafeCard,
    background: studyFriendBackground,
    avatar: studyFriendAvatar,
  },
]
