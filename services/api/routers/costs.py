from fastapi import APIRouter

from services.costs.service import read_aws_costs, read_pinecone_costs

router = APIRouter()


@router.get("/aws")
def aws_costs():
    return read_aws_costs()


@router.get("/pinecone")
def pinecone_costs():
    return read_pinecone_costs()
