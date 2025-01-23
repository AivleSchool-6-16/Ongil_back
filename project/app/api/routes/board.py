# 정보 게시판
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
import mysql.connector
import traceback


router = APIRouter()

def get_connection():
    return mysql.connector.connect(
        host="ongil-1.criqwcemqnaf.ap-northeast-2.rds.amazonaws.com",
        user="root",     
        password="aivle202406",
        database="ongildb" 
    )

class PostWriteModel(BaseModel):
    title: str
    text: str
    jurisdiction: str

class CommentWriteModel(BaseModel):
    post_id: int
    comment_text: str
    commenter: str


@router.get("/postall") # 게시글 전체 조회
def view_posts():
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        sql = "SELECT * FROM post"
        cursor.execute(sql)
        rows = cursor.fetchall()

        cursor.close()
        conn.close()

        return {
            "success": True,
            "data": rows
        }

    except Exception:
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="게시판 전체 조회 실패"
        )
    
@router.get("/postSearch") # 게시판 검색
def post_search(q: str = ""):
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        sql = """
            SELECT *
            FROM post
            WHERE title LIKE %s OR jurisdiction LIKE %s
        """
        search_keyword = f"%{q}%"
        cursor.execute(sql, (search_keyword, search_keyword))
        rows = cursor.fetchall()

        cursor.close()
        conn.close()

        return {
            "success": True,
            "data": rows
        }

    except Exception:
        traceback.print_exc() 
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="게시판 검색 실패"
        )

@router.get("/postdetail") # 게시글 페이지
def post_detail(post_id: int):
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        # (1) 게시글 정보
        post_sql = "SELECT * FROM post WHERE id = %s"
        cursor.execute(post_sql, (post_id,))
        post = cursor.fetchone()

        if not post:
            cursor.close()
            conn.close()
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="해당 게시글을 찾을 수 없습니다."
            )

        # (2) 댓글 정보
        comment_sql = "SELECT * FROM comments WHERE post_id = %s"
        cursor.execute(comment_sql, (post_id,))
        comments = cursor.fetchall()

        cursor.close()
        conn.close()

        return {
            "success": True,
            "data": {
                "post": post,
                "comments": comments
            }
        }

    except HTTPException as he:
        # 이미 처리한 HTTPException
        raise he

    except Exception:
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="게시판 상세보기 실패"
        )


@router.post("/post_write") # 게시글 작성
def post_write(post_data: PostWriteModel):
    try:
        conn = get_connection()
        cursor = conn.cursor()

        sql = """
            INSERT INTO post (title, text, jurisdiction, date)
            VALUES (%s, %s, %s, NOW())
        """
        cursor.execute(sql, (
            post_data.title,
            post_data.text,
            post_data.jurisdiction
        ))
        conn.commit()

        insert_id = cursor.lastrowid

        cursor.close()
        conn.close()

        return {
            "success": True,
            "message": "게시글이 정상적으로 작성되었습니다.",
            "insertId": insert_id
        }

    except Exception:
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="게시글 작성 실패"
        )
    
@router.post("/comment_write") # 댓글 작성
def write_comment(comment_data: CommentWriteModel):
    try:
        conn = get_connection()
        cursor = conn.cursor()

        sql = """
            INSERT INTO comment (post_id, comment_text, commenter, date)
            VALUES (%s, %s, %s, NOW())
        """ # 번호, 내용, 작성자, 날짜
        cursor.execute(sql, (
            comment_data.post_id,
            comment_data.comment_text,
            comment_data.commenter
        ))
        conn.commit()

        cursor.close()
        conn.close()

        return {
            "success": True,
            "message": "댓글 작성 완료"
        }

    except Exception:
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="댓글 작성 실패"
        )

@router.delete("/comment_delete/{comment_id}") # 댓글 삭제
def comment_delete(comment_id: int):
    try:
        conn = get_connection()
        cursor = conn.cursor()

        sql = "DELETE FROM comment WHERE id = %s"
        cursor.execute(sql, (comment_id,))
        conn.commit()

        cursor.close()
        conn.close()

        return {
            "success": True,
            "message": "댓글이 삭제되었습니다."
        }

    except Exception:
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="댓글 삭제 실패"
        )
    
@router.delete("/post_delete/{post_id}") # 게시글 삭제 / db 제작시 cascade 사용할 것
def post_delete(post_id: int):
    try:
        conn = get_connection()
        cursor = conn.cursor()

        # (1) 게시글 삭제
        sql = "DELETE FROM post WHERE id = %s"
        cursor.execute(sql, (post_id,))
        conn.commit()

        cursor.close()
        conn.close()

        return {
            "success": True,
            "message": "게시글이 삭제되었습니다."
        }

    except Exception:
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="게시글 삭제 실패"
        )